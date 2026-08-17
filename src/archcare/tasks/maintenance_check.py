"""
Maintenance check task for archcare.

Monitors task schedule status and alerts users to tasks needing attention.
"""

from datetime import datetime, timedelta

from loguru import logger

from archcare.config import (
    AppSettings,
    ConfigLoader,
    TaskConfig,
    TaskState,
    TaskStatus,
    TaskType,
)
from archcare.core import (
    IssueSeverity,
    MaintenanceCheckDetails,
    MaintenanceCheckSummary,
    MaintenanceIssue,
    TaskResult,
    TaskScheduleInfo,
    TaskScheduler,
)

from .base import BaseTask


class MaintenanceCheckTask(BaseTask):
    """
    Check for due and overdue maintenance tasks.

    This task monitors all enabled tasks and reports:
    - Manual tasks that are due or overdue
    - Automated tasks that have failed
    - Automated tasks with broken timers (overdue with no attempts)
    - Tasks that have never been run
    """

    def __init__(
        self,
        config: TaskConfig,
        settings: AppSettings,
        *args,
        **kwargs,
    ):
        """
        Initialize maintenance check task.

        Args:
            config: Task configuration
            settings: Application settings
        """
        super().__init__(config, settings, *args, **kwargs)

        # Initialize issue lists
        self._info_issues: list[MaintenanceIssue] = []
        self._warning_issues: list[MaintenanceIssue] = []
        self._critical_issues: list[MaintenanceIssue] = []

        # Initialize loader and load fresh state/tasks
        self.config_loader = ConfigLoader(user=settings.user)
        self.state = self.config_loader.load_state()
        self.tasks_config = self.config_loader.load_tasks()
        self.scheduler = TaskScheduler(self.tasks_config, self.state)

    def execute(self) -> TaskResult[MaintenanceCheckDetails]:
        """
        Execute maintenance check.

        Returns:
            TaskResult with maintenance check details
        """

        logger.info("Starting maintenance check")

        # Get all enabled tasks
        enabled_tasks = self.tasks_config.get_enabled_tasks()
        total_tasks_monitored = len(enabled_tasks)

        logger.info(f"Checking {total_tasks_monitored} enabled tasks")

        # Check each task
        for task_name, task_config in enabled_tasks.items():
            # Skip checking maintenance-check itself
            if task_name == self.config.name:
                continue

            task_issues = self._check_task(task_name, task_config)

            # Categorize issues by severity
            self._categorize_issues(task_issues)

        summary = MaintenanceCheckSummary(
            total_tasks_monitored=total_tasks_monitored,
            critical_count=len(self._critical_issues),
            warning_count=len(self._warning_issues),
            info_count=len(self._info_issues),
        )

        # Determine overall status
        error_message = None
        if self._critical_issues:
            error_message = f"{len(self._critical_issues)} critical issues found"
            status = TaskStatus.FAILURE
            logger.error(error_message)
        elif self._warning_issues:
            status = TaskStatus.PARTIAL
            logger.warning(f"{len(self._warning_issues)} warning issues found")
        elif self._info_issues:
            status = TaskStatus.SUCCESS
            logger.success(
                f"{len(self._info_issues)} info issues found. No immediate attention required"
            )
        else:
            status = TaskStatus.SUCCESS
            logger.success("No issues found")

        logger.info("Maintenance check complete")

        details = MaintenanceCheckDetails(
            critical_issues=self._critical_issues,
            warning_issues=self._warning_issues,
            info_issues=self._info_issues,
            summary=summary,
        )

        return TaskResult(
            status=status,
            message=summary.summary_message,
            details=details,
            error=error_message,
        )

    def _categorize_issues(self, issues: list[MaintenanceIssue]):
        for issue in issues:
            match issue.severity:
                case IssueSeverity.CRITICAL:
                    self._critical_issues.append(issue)
                case IssueSeverity.WARNING:
                    self._warning_issues.append(issue)
                case IssueSeverity.INFO:
                    self._info_issues.append(issue)

    def _check_task(self, task_name: str, task_config: TaskConfig) -> list[MaintenanceIssue]:
        """
        Check a single task for issues.

        Args:
            task_name: Name of the task
            task_config: Task configuration

        Returns:
            List of issues found (maybe empty)
        """
        issues: list[MaintenanceIssue] = []

        # Get task state and schedule info
        task_state = self.state.get_task_state(task_name)
        schedule_info = self.scheduler.get_schedule_info(task_name)
        days_overdue = schedule_info.days_overdue

        # Check for different issue types

        # 1. Never-run tasks
        if task_state.last_run is None:
            issues.append(
                MaintenanceIssue(
                    task_name=task_name,
                    severity=IssueSeverity.INFO,
                    description="Task has never been executed",
                    days_overdue=None,
                    last_run=None,
                    last_status=None,
                    recommendation=f"Run manually: archcare task run {task_name}",
                )
            )
            return issues  # Don't check further for never-run tasks

        # 2. Manual tasks - check if due/overdue
        if task_config.task_type == TaskType.MANUAL:
            self._check_overdue_task(
                days_overdue, issues, schedule_info, task_config, task_name, task_state
            )

        # 3. Automated tasks - check for failures and broken timers
        elif task_config.task_type == TaskType.AUTOMATED:
            # Check if last run failed
            if task_state.last_status == TaskStatus.FAILURE:
                # Check if task is now overdue (retry failed)
                self._check_failed_automated_task(
                    days_overdue, issues, schedule_info, task_name, task_state
                )

            # Check for broken timer (overdue beyond reasonable threshold)
            timer_threshold_days = task_config.frequency * 1.5
            self._check_broken_timer(
                days_overdue, issues, timer_threshold_days, task_name, task_state
            )

        return issues

    def _check_overdue_task(
        self,
        days_overdue: int,
        issues: list[MaintenanceIssue],
        schedule_info: TaskScheduleInfo,
        task_config: TaskConfig,
        task_name: str,
        task_state: TaskState,
    ):
        """
        Checks whether a manual task is overdue and appends
        the MaintenanceIssue to the issues list if so.

        Args:
            days_overdue: Number of days overdue.
            issues: List of maintenance issues found
            schedule_info: Schedule info for the task being checked
            task_config: The TaskConfig instance for the task being checked
            task_name: Name of the task
            task_state: The current state of the task
        """
        if schedule_info.is_due:
            severity = self._determine_severity(days_overdue)

            issues.append(
                MaintenanceIssue(
                    task_name=task_name,
                    severity=severity,
                    description=self._format_overdue_description(task_config, days_overdue),
                    days_overdue=days_overdue,
                    last_run=task_state.last_run,
                    last_status=task_state.last_status,
                    recommendation=f"Run now: archcare task run {task_name}",
                )
            )

    @staticmethod
    def _check_broken_timer(
        days_overdue: int,
        issues: list[MaintenanceIssue],
        timer_threshold_days: float,
        task_name: str,
        task_state: TaskState,
    ):
        """
        Checks whether the systemd timer for an automated task is broken and appends
        the MaintenanceIssue to the issues list if so.

        Args:
            days_overdue: Number of days overdue.
            issues: List of maintenance issues found
            timer_threshold_days: The threshold for the days overdue
             to be considered critical
            task_name: Name of the task
            task_state: The current state of the task
        """

        if days_overdue > timer_threshold_days:
            issues.append(
                MaintenanceIssue(
                    task_name=task_name,
                    severity=IssueSeverity.CRITICAL,
                    description=(
                        f"Automated task is severely overdue ({days_overdue} days). "
                        f"Timer may be broken or disabled."
                    ),
                    days_overdue=days_overdue,
                    last_run=task_state.last_run,
                    last_status=task_state.last_status,
                    recommendation=(
                        f"Check timer: systemctl status archcare@{task_name}.timer\n"
                        "Enable timer: sudo systemctl enable --now "
                        f"archcare@{task_name}.timer"
                    ),
                )
            )

    def _check_failed_automated_task(
        self,
        days_overdue: int,
        issues: list[MaintenanceIssue],
        schedule_info: TaskScheduleInfo,
        task_name: str,
        task_state: TaskState,
    ):
        """
        Check whether a failed automated task is overdue and appends
        the MaintenanceIssue to the issues list if so.

        Args:
            days_overdue: Number of days overdue.
            issues: List of maintenance issues found
            schedule_info: Schedule info for the task being checked
            task_name: Name of the task
            task_state: The current state of the task
        """
        if schedule_info.is_due:
            issues.append(
                MaintenanceIssue(
                    task_name=task_name,
                    severity=IssueSeverity.WARNING,
                    description=(
                        f"Automated task failed and is now overdue "
                        f"(last run: {self._format_time_ago(task_state.last_run)})"
                    ),
                    days_overdue=days_overdue,
                    last_run=task_state.last_run,
                    last_status=task_state.last_status,
                    recommendation=(
                        f"Check timer status: systemctl status archcare@{task_name}.timer\n"
                        f"Check logs: archcare logs {task_name}"
                    ),
                )
            )

    def _determine_severity(self, days_overdue: int) -> IssueSeverity:
        """
        Determine severity based on days overdue.

        Args:
            days_overdue: Number of days overdue.

        Returns:
            Appropriate severity level
        """
        critical_threshold = self.settings.maintenance_check.critical_threshold_days
        warning_threshold = self.settings.maintenance_check.warning_threshold_days

        if days_overdue >= critical_threshold:
            # Task severely overdue
            return IssueSeverity.CRITICAL
        elif days_overdue >= warning_threshold:
            # Task overdue but not critical
            return IssueSeverity.WARNING
        else:
            # Task overdue but no immediate attention is required
            return IssueSeverity.INFO

    @staticmethod
    def _format_overdue_description(task_config: TaskConfig, days_overdue: int) -> str:
        """
        Format a description for an overdue task.

        Args:
            task_config: Task configuration
            days_overdue: Days overdue

        Returns:
            Formatted description
        """
        if days_overdue == 0:
            return f"Task `{task_config.name}` is due today"
        elif days_overdue == 1:
            return f"Task `{task_config.name}` is overdue by 1 day"
        else:
            return f"Task `{task_config.name}` is overdue by {days_overdue} days"

    @staticmethod
    def _format_time_ago(timestamp: datetime | None) -> str:
        """
        Format a timestamp as human-readable time ago.

        Args:
            timestamp: Timestamp to format

        Returns:
            Human-readable string like "2 days ago"
        """
        if timestamp is None:
            return "never"

        delta = datetime.now() - timestamp

        if delta.days > 0:
            if delta.days == 1:
                return "1 day ago"
            return f"{delta.days} days ago"

        hours = delta.seconds // 3600
        if hours > 0:
            if hours == 1:
                return "1 hour ago"
            return f"{hours} hours ago"

        minutes = delta.seconds // 60
        if minutes > 0:
            if minutes == 1:
                return "1 minute ago"
            return f"{minutes} minutes ago"

        return "just now"

    def post_execute(self, result: TaskResult[MaintenanceCheckDetails]) -> None:
        """
        Post-execution actions: send notifications and show terminal output.

        Args:
            result: The result from execute()
        """
        details = result.details
        if not details:
            # Shouldn't happen, but being defensive
            raise ValueError("`details` should not be `None`")

        # Send notification if enabled
        if self.settings.maintenance_check.show_notifications:
            self._send_notification(details)

        # Save report if output_mode requires it
        output_mode = self.settings.maintenance_check.output_mode
        if output_mode in ("file", "both"):
            self._save_report(details, result.timestamp, result.status)

    def _send_notification(self, details: MaintenanceCheckDetails):
        """
        Send desktop notification based on check results.

        Args:
            details: Maintenance check details
        """

        notification_level = self.settings.maintenance_check.notification_level

        # Severity threshold map to check against
        severity_map = {"info": 0, "warning": 1, "critical": 2}
        severity = IssueSeverity.INFO  # Default severity

        summary = details.summary

        if summary.has_issues:
            if details.critical_issues:
                severity = IssueSeverity.CRITICAL
            elif details.warning_issues:
                severity = IssueSeverity.WARNING
            elif details.info_issues:
                severity = IssueSeverity.INFO
            else:
                # This should never happen
                raise ValueError("details cannot have issues and empty issues at the same time")

            should_notify = severity_map.get(str(severity), -1) >= severity_map.get(
                notification_level, -1
            )
        else:
            should_notify = False

        if not should_notify:
            logger.debug("No notification sent (below threshold)")
            return

        # Send notification
        if self.notification_manager:
            self.notification_manager.send_maintenance_notification(
                severity=severity,
                tasks_count=summary.total_issues,
                summary=summary.summary_message,
            )

    def _save_report(
        self, details: MaintenanceCheckDetails, timestamp: datetime, status: TaskStatus
    ):
        """
        Save maintenance check report to file.

        Args:
            details: Maintenance check details
            timestamp: Report generation timestamp
            status: Status of maintenance check
        """
        # Generate report filename with timestamp
        timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")
        report_file = self.settings.report_dir / f"maintenance-check_{timestamp_str}.txt"

        # Build report content
        lines = [
            "=" * 80,
            "Archcare Maintenance Check Report",
            f"Generated: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 80,
            "\n",
            f"Status: {str(status).upper()}",
            f"Tasks Monitored: {details.summary.total_tasks_monitored}",
        ]

        if tasks_needing_attention := details.tasks_needing_attention:
            lines.append("Tasks needing attention:")
            for maintenance_issue in tasks_needing_attention:
                lines.append(
                    f"  - {maintenance_issue.task_name} ({str(maintenance_issue.severity).upper()})"
                )
            lines.append("\n")

        if not details.summary.has_issues:
            lines.append("✓ No maintenance issues found! Your system is healthy :)")
            lines.append("\n")
        else:
            # Add issues by severity
            if details.critical_issues:
                self._add_issues_section(lines, "🟥 CRITICAL ISSUES", details.critical_issues)

            if details.warning_issues:
                self._add_issues_section(lines, "🟨 WARNING ISSUES", details.warning_issues)

            if details.info_issues:
                self._add_issues_section(lines, "🟦 INFORMATION", details.info_issues)

        lines.append("End of report")
        lines.append("=" * 80)

        # Write report
        report_file.write_text("\n".join(lines))
        logger.info(f"Maintenance report saved to: {report_file}")

        # Clean up old reports based on retention
        self._cleanup_old_reports()

    def _add_issues_section(
        self, lines: list[str], header_title: str, issues: list[MaintenanceIssue]
    ):
        """
        Adds the issues section to the report file

        Args:
            lines: Previously built text lines to append to
            header_title: The title of the header
            issues: The list of maintenance issues
        """
        lines.append(header_title)
        lines.append("-" * 80)
        for issue in issues:
            lines.extend(self._format_issue_text(issue))

    @staticmethod
    def _format_issue_text(issue: MaintenanceIssue) -> list[str]:
        """
        Format an issue as text lines.

        Args:
            issue: Issue to format

        Returns:
            List of text lines
        """
        lines = [f"Task: {issue.task_name}", f"Issue: {issue.description}"]
        if issue.days_overdue is not None:
            lines.append(f"Days Overdue: {issue.days_overdue}")
        if issue.last_run:
            lines.append(f"Last Run: {issue.last_run.strftime('%Y-%m-%d %H:%M:%S')}")
        if issue.last_status:
            lines.append(f"Last Status: {issue.last_status.value}")
        lines.append(f"Recommendation: {issue.recommendation}")
        lines.append("\n")
        return lines

    def _cleanup_old_reports(self):
        """Clean up old maintenance check reports based on retention setting."""
        retention_days = self.settings.maintenance_check.report_retention_days
        cutoff_date = datetime.now() - timedelta(days=retention_days)

        if not self.settings.report_dir.exists():
            return

        deleted_count = 0
        for report_file in self.settings.report_dir.glob("maintenance-check_*.txt"):
            try:
                # Get file modification time
                mtime = datetime.fromtimestamp(report_file.stat().st_mtime)

                if mtime < cutoff_date:
                    report_file.unlink()
                    deleted_count += 1
                    logger.debug(f"Deleted old report: {report_file.name}")
            except Exception as e:
                logger.warning(f"Failed to delete report {report_file.name}: {e}")

        if deleted_count > 0:
            logger.info(
                f"Cleaned up {deleted_count} old maintenance report(s) "
                f"(retention: {retention_days} days)"
            )
