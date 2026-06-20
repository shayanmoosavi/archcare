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
from archcare.core.models import (
    IssueSeverity,
    MaintenanceCheckResult,
    MaintenanceIssue,
    TaskResult,
)
from archcare.core.scheduler import TaskScheduleInfo, TaskScheduler
from archcare.tasks.base import BaseTask
from archcare.utils.notifications import get_notification_manager


class MaintenanceCheckTask(BaseTask):
    """
    Check for due and overdue maintenance tasks.

    This task monitors all enabled tasks and reports:
    - Manual tasks that are due or overdue
    - Automated tasks that have failed
    - Automated tasks with broken timers (overdue with no attempts)
    - Tasks that have never been run
    """

    def __init__(self, config: TaskConfig, settings: AppSettings):
        """
        Initialize maintenance check task.

        Args:
            config: Task configuration
            settings: Application settings
        """
        super().__init__(config, settings)

        # MaintenanceCheckResult instance to store the necessary information, initialized to None
        self.maintenance_check_result: MaintenanceCheckResult | None = None

        # Initialize loader and load fresh state/tasks
        self.config_loader = ConfigLoader(user=settings.user)
        self.state = self.config_loader.load_state()
        self.tasks_config = self.config_loader.load_tasks()
        self.scheduler = TaskScheduler(self.tasks_config, self.state)

    def execute(self) -> TaskResult:
        """
        Execute maintenance check.

        Returns:
            MaintenanceCheckResult with categorized issues
        """

        logger.info("Starting maintenance check")

        # Initialize result
        result = MaintenanceCheckResult(  # type: ignore[call-arg]
            task_name=self.config.name,
            status=TaskStatus.SUCCESS,  # Will update based on findings
        )

        # Get all enabled tasks
        enabled_tasks = self.tasks_config.get_enabled_tasks()
        result.total_tasks_monitored = len(enabled_tasks)

        logger.info(f"Checking {result.total_tasks_monitored} enabled tasks")

        # Check each task
        for task_name, task_config in enabled_tasks.items():
            # Skip checking maintenance-check itself
            if task_name == self.config.name:
                continue

            issues = self._check_task(task_name, task_config)

            # Categorize issues by severity
            self._categorize_issues(issues, result)

        # Determine overall status
        if result.critical_issues:
            result.error_message = (
                f"{len(result.critical_issues)} critical issues found"
            )
            result.status = TaskStatus.FAILURE
            logger.error(result.error_message)
        elif result.warning_issues:
            result.status = TaskStatus.PARTIAL
            logger.warning(f"{len(result.warning_issues)} warning issues found")
        elif result.info_issues:
            result.status = TaskStatus.SUCCESS
            logger.success(
                f"{len(result.info_issues)} info issues found. No immediate attention required"
            )
        else:
            result.status = TaskStatus.SUCCESS
            logger.success("No issues found")

        logger.info("Maintenance check complete")

        self.maintenance_check_result = result
        task_result = result.to_task_result()
        task_result.details["maintenance_result"] = result
        return task_result

    @staticmethod
    def _categorize_issues(
        issues: list[MaintenanceIssue], result: MaintenanceCheckResult
    ):
        for issue in issues:
            match issue.severity:
                case IssueSeverity.CRITICAL:
                    result.critical_issues.append(issue)
                case IssueSeverity.WARNING:
                    result.warning_issues.append(issue)
                case IssueSeverity.INFO:
                    result.info_issues.append(issue)

    def _check_task(
        self, task_name: str, task_config: TaskConfig
    ) -> list[MaintenanceIssue]:
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

        # Calculate days overdue (negative if not due yet)
        days_overdue = (
            (datetime.now() - schedule_info.next_due).days
            if schedule_info.next_due
            else None
        )

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
        days_overdue: int | None,
        issues: list[MaintenanceIssue],
        schedule_info: TaskScheduleInfo,
        task_config: TaskConfig,
        task_name: str,
        task_state: TaskState,
    ):
        """
        Checks whether a manual task is overdue and appends the MaintenanceIssue to the issues list if so.

        Args:
            days_overdue: Number of days overdue. None if never run
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
                    description=self._format_overdue_description(
                        task_config, days_overdue
                    ),
                    days_overdue=days_overdue,
                    last_run=task_state.last_run,
                    last_status=task_state.last_status,
                    recommendation=f"Run now: archcare task run {task_name}",
                )
            )

    @staticmethod
    def _check_broken_timer(
        days_overdue: int | None,
        issues: list[MaintenanceIssue],
        timer_threshold_days: float,
        task_name: str,
        task_state: TaskState,
    ):
        """
        Checks whether the systemd timer for an automated task is broken and appends the MaintenanceIssue
        to the issues list if so.

        Args:
            days_overdue: Number of days overdue. None if never run
            issues: List of maintenance issues found
            timer_threshold_days: The threshold for the days overdue to be considered critical
            task_name: Name of the task
            task_state: The current state of the task

        Raises:
            ValueError: If days_overdue is None
        """

        if days_overdue:
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
                            f"Enable timer: sudo systemctl enable --now archcare@{task_name}.timer"
                        ),
                    )
                )
        else:
            raise ValueError("days overdue should not be `None`")

    def _check_failed_automated_task(
        self,
        days_overdue: int | None,
        issues: list[MaintenanceIssue],
        schedule_info: TaskScheduleInfo,
        task_name: str,
        task_state: TaskState,
    ):
        """
        Check whether a failed automated task is overdue and appends the MaintenanceIssue to the issues list if so.

        Args:
            days_overdue: Number of days overdue. None if never run
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

    def _determine_severity(self, days_overdue: int | None) -> IssueSeverity:
        """
        Determine severity based on days overdue.

        Args:
            days_overdue: Number of days overdue. None if never run

        Returns:
            Appropriate severity level
        """
        critical_threshold = self.settings.maintenance_check.critical_threshold_days
        warning_threshold = self.settings.maintenance_check.warning_threshold_days

        if not days_overdue:
            return IssueSeverity.INFO
        else:
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
    def _format_overdue_description(
        task_config: TaskConfig, days_overdue: int | None
    ) -> str:
        """
        Format a description for an overdue task.

        Args:
            task_config: Task configuration
            days_overdue: Days overdue

        Returns:
            Formatted description

        Raises:
            ValueError: If days_overdue is None
        """
        if days_overdue:
            if days_overdue == 0:
                return f"Task `{task_config.name}` is due today"
            elif days_overdue == 1:
                return f"Task `{task_config.name}` is overdue by 1 day"
            else:
                return f"Task `{task_config.name}` is overdue by {days_overdue} days"
        else:
            raise ValueError("days overdue should not be `None`")

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

    def post_execute(self, result: TaskResult) -> None:
        """
        Post-execution actions: send notifications and show terminal output.

        Args:
            result: The result from execute()
        """
        check_result = self.maintenance_check_result
        if not check_result:
            # Shouldn't happen, but being defensive
            raise ValueError("`maintenance_check_result` should not be `None`")

        # Send notification if enabled
        if self.settings.maintenance_check.show_notifications:
            self._send_notification(check_result)

        # Save report if output_mode requires it
        output_mode = self.settings.maintenance_check.output_mode
        if output_mode in ("file", "both"):
            self._save_report(check_result)

    def _send_notification(self, check_result: MaintenanceCheckResult):
        """
        Send desktop notification based on check results.

        Args:
            check_result: Maintenance check result
        """
        notification_level = self.settings.maintenance_check.notification_level

        # Severity threshold map to check against
        severity_map = {"info": 0, "warning": 1, "critical": 2}
        severity = IssueSeverity.INFO  # Default severity

        critical_issues = check_result.get_issues_by_severity(IssueSeverity.CRITICAL)
        warning_issues = check_result.get_issues_by_severity(IssueSeverity.WARNING)
        info_issues = check_result.get_issues_by_severity(IssueSeverity.INFO)

        if check_result.has_issues:
            if critical_issues:
                severity = IssueSeverity.CRITICAL
            elif warning_issues:
                severity = IssueSeverity.WARNING
            elif info_issues:
                severity = IssueSeverity.INFO
            else:
                # This should never happen
                raise ValueError(
                    "result cannot have issues and empty issues at the same time"
                )

            should_notify = severity_map.get(str(severity), -1) >= severity_map.get(
                notification_level, -1
            )
        else:
            should_notify = False

        if not should_notify:
            logger.debug("No notification sent (below threshold)")
            return

        # Send notification
        manager = get_notification_manager()
        manager.send_maintenance_notification(
            severity=severity,
            tasks_count=len(check_result.all_issues),
            summary=check_result.summary_message,
        )

    def _save_report(self, result: MaintenanceCheckResult):
        """
        Save maintenance check report to file.

        Args:
            result: Maintenance check result
        """
        # Generate report filename with timestamp
        timestamp = result.timestamp.strftime("%Y%m%d_%H%M%S")
        report_file = self.settings.report_dir / f"maintenance-check_{timestamp}.txt"

        # Build report content
        lines = [
            "=" * 80,
            "Archcare Maintenance Check Report",
            f"Generated: {result.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 80,
            "\n",
            f"Status: {result.status.value.upper()}",
            f"Tasks Monitored: {result.total_tasks_monitored}",
        ]

        if result.tasks_needing_attention:
            lines.append("Tasks needing attention:")
            for maintenance_issue in result.tasks_needing_attention:
                lines.append(
                    f"  - {maintenance_issue.task_name} ({str(maintenance_issue.severity).upper()})"
                )
            lines.append("\n")

        if not result.has_issues:
            lines.append("✓ No maintenance issues found! Your system is healthy :)")
            lines.append("\n")
        else:
            # Add issues by severity
            if result.critical_issues:
                self._add_issues_section(
                    lines, "🟥 CRITICAL ISSUES", result.critical_issues
                )

            if result.warning_issues:
                self._add_issues_section(
                    lines, "🟨 WARNING ISSUES", result.warning_issues
                )

            if result.info_issues:
                self._add_issues_section(lines, "🟦 INFORMATION", result.info_issues)

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
