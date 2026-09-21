"""
Maintenance check task for Archcare.

This module provides `MaintenanceCheckTask`, a scheduler-aware task that monitors the status of all
enabled maintenance tasks and reports which ones need attention. It is registered in the static task
registry and exposed to users as the `maintenance-check` command.

Unlike other tasks, this task does not perform maintenance itself. Instead it inspects task
configuration and persistent state (via [`TaskScheduler`][]) and emits categorized
[`MaintenanceIssue`][] findings:

- **Critical**: automated tasks severely overdue past the timer threshold (frequency × 1.5 days) —
    the systemd timer is likely broken or disabled.
- **Warning**: manual tasks overdue past `warning_threshold_days`, or automated tasks that failed
    and are now due for a retry.
- **Info**: tasks that have never been run, or manual tasks slightly overdue (below the warning
    threshold).

The overall result status is `FAILURE` if any critical issue exists, `PARTIAL` if only warnings,
and `SUCCESS` otherwise. In `post_execute()`, the task may additionally send a desktop notification
(respecting the configured `notification_level`) and write a timestamped text report to
`~/.local/state/archcare/reports/` (when `output_mode` is `"file"` or `"both"`), pruning reports
older than `report_retention_days`.

!!! note "Self-exclusion"
    The `maintenance-check` task never monitors itself, preventing a
    self-referential "overdue" report.

See Also:
    - [`BaseTask`][]: Abstract workflow this task implements
    - [`TaskScheduler`][]: Computes due/overdue status
    - [`TaskResult`][]: The structured result object that the task returns
    - [`MaintenanceCheckDetails`][]: Details schema produced by this task
    - [`MaintenanceCheckSettings`][archcare.config.models.MaintenanceCheckSettings]:
        Thresholds, notification, and report settings
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
    BaseTask,
    IssueSeverity,
    MaintenanceCheckDetails,
    MaintenanceCheckSummary,
    MaintenanceIssue,
    TaskResult,
    TaskScheduleInfo,
    TaskScheduler,
)


class MaintenanceCheckTask(BaseTask):
    """
    Check for due and overdue maintenance tasks and report findings by severity.

    This task monitors all enabled tasks and reports:

    - Manual tasks that are due or overdue
    - Automated tasks that have failed
    - Automated tasks with broken timers (overdue past frequency × 1.5 days)
    - Tasks that have never been run

    Findings are categorized into `info`, `warning`, and `critical` buckets (see `self._check_task`
    in source code) and aggregated into a [`MaintenanceCheckSummary`][].

    !!! note "Fresh state"
        Unlike most tasks, `MaintenanceCheckTask` builds its own [`ConfigLoader`][] at instantiation
        time and loads tasks/state eagerly, rather than deferring to the
        executor. This guarantees the report reflects the latest on-disk state
        even when other tasks have run in the same invocation.

    See Also:
        - [`MaintenanceCheckSettings`][archcare.config.models.MaintenanceCheckSettings]:
            Configurable thresholds (`critical_threshold_days`, `warning_threshold_days`),
            notification, and report options
    """

    def __init__(
        self,
        config: TaskConfig,
        settings: AppSettings,
        *args,
        **kwargs,
    ):
        """
        Initialize the maintenance check task and load current schedule state.

        Sets up empty issue accumulator lists and eagerly constructs a [`ConfigLoader`][] (bound to
        the target user) plus a [`TaskScheduler`][] seeded with the freshly loaded tasks
        configuration and persisted state.

        Args:
            config (TaskConfig): Task-specific configuration (e.g., enabled, frequency).
            settings (AppSettings): Application-wide settings, including the
                [`MaintenanceCheckSettings`][archcare.config.models.MaintenanceCheckSettings]
                thresholds and the target `user`.

        Other Args:
            *args (tuple): Forwarded to `BaseTask.__init__()`.
            **kwargs (dict): Forwarded to `BaseTask.__init__()`.

        Side Effects:
            - Initializes `_info_issues`, `_warning_issues`, and
                `_critical_issues` to empty lists.
            - Reads `state.json` and `tasks.toml` from disk via the loader.
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
        Execute the maintenance check across all enabled tasks.

        Iterates over every enabled task (skipping the `maintenance-check` task itself), collects
        per-task issues via `self._check_task`, buckets them by severity, and selects the overall
        outcome:

        - `FAILURE` when any critical issue was found (also set as `error`)
        - `PARTIAL` when only warnings were found
        - `SUCCESS` when only info-level findings or nothing at all

        Returns:
            (TaskResult[MaintenanceCheckDetails]):
                Result whose `details` is a `MaintenanceCheckDetails` containing the categorized
                issue lists, a [`MaintenanceCheckSummary`][] (counts plus `total_tasks_monitored`),
                and a human-readable message from `summary.summary_message`.

        Side Effects:
            Emits Loguru log messages at `info`/`warning`/`error`/`success` levels summarizing
            the findings.
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

    def _categorize_issues(self, issues: list[MaintenanceIssue]) -> None:
        """
        Bucket issues into the per-severity accumulator lists.

        Dispatches each issue to `self._critical_issues`, `self._warning_issues`, or
        `self._info_issues` according to its `IssueSeverity`.

        Args:
            issues (list[MaintenanceIssue]): Issues found for a single task,
                as returned by `self._check_task`.

        Side Effects:
            Mutates `self._critical_issues`, `self._warning_issues`, and
                `self._info_issues`.
        """
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
        Check a single task for issues based on its type and state.

        Applies the following checks in order (short-circuiting after the first
        that produces findings):

        1. **Never run** (`last_run` is `None`): emits an `INFO` issue and returns immediately.
        2. **Manual tasks**: checked for due/overdue status via `self._check_overdue_task`.
        3. **Automated tasks**: if the last run failed and the task is due, a `WARNING` is emitted
            via `self._check_failed_automated_task`; additionally, if overdue past `frequency × 1.5`
            days, a `CRITICAL` "broken timer" issue is emitted via `self._check_broken_timer`.

        Args:
            task_name (str): Name of the task being checked.
            task_config (TaskConfig): Configuration of the task being checked.

        Returns:
            list[MaintenanceIssue]: Issues found for this task (possibly empty).
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
        Check whether a manual task is due or overdue.

        If the task's schedule indicates it is due, appends a `MaintenanceIssue` whose severity is
        determined by `self._determine_severity` and whose recommendation suggests running the task
        manually.

        Args:
            days_overdue (int): Number of days the task is overdue (0 = due today).
            issues (list[MaintenanceIssue]): Accumulator list to append the
                issue to when the task is due.
            schedule_info (TaskScheduleInfo): Schedule info for the task being
                checked (provides the `is_due` flag).
            task_config (TaskConfig): The task configuration of the task being
                checked (used for the description text).
            task_name (str): Name of the task being checked.
            task_state (TaskState): Current persisted state of the task
                (provides `last_run`/`last_status` for the issue).

        Side Effects:
            Appends to `issues` when the task is due.
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
        Check whether the systemd timer for an automated task is broken.

        A timer is considered broken when the task is overdue by more than `timer_threshold_days`
        (typically `frequency × 1.5`). Emits a `CRITICAL` issue with recommendations to
        inspect/enable the `archcare@<task>.timer` unit.

        Args:
            days_overdue (int): Number of days the task is overdue.
            issues (list[MaintenanceIssue]): Accumulator list to append the
                issue to when the timer is considered broken.
            timer_threshold_days (float): Overdue threshold (in days) beyond
                which the timer is deemed broken.
            task_name (str): Name of the task being checked.
            task_state (TaskState): Current persisted state of the task
                (provides `last_run`/`last_status` for the issue).

        Side Effects:
            Appends to `issues` when the task exceeds the timer threshold.
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
        Check whether a failed automated task is due for a retry.

        If the task's schedule indicates it is due, appends a `WARNING` `MaintenanceIssue` noting
        that the last run failed and the task is overdue, with recommendations to inspect the timer
        and logs.

        Args:
            days_overdue (int): Number of days the task is overdue.
            issues (list[MaintenanceIssue]): Accumulator list to append the
                issue to when the failed task is due.
            schedule_info (TaskScheduleInfo): Schedule info for the task being
                checked (provides the `is_due` flag).
            task_name (str): Name of the task being checked.
            task_state (TaskState): Current persisted state of the task
                (provides `last_run`/`last_status` for the issue).

        Side Effects:
            Appends to `issues` when the failed task is due.
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
        Determine issue severity based on days overdue.

        Compares against the configurable thresholds in `MaintenanceCheckSettings`:

        - `>= critical_threshold_days` (default 7): `CRITICAL`
        - `>= warning_threshold_days` (default 0): `WARNING`
        - otherwise: `INFO`

        Args:
            days_overdue (int): Number of days the task is overdue.

        Returns:
            IssueSeverity: The severity level appropriate for the given overdue duration.
        """
        critical_threshold = self.settings.maintenance_check.critical_threshold_days
        warning_threshold = self.settings.maintenance_check.warning_threshold_days

        if days_overdue >= critical_threshold:
            # Task severely overdue
            return IssueSeverity.CRITICAL
        if days_overdue >= warning_threshold:
            # Task overdue but not critical
            return IssueSeverity.WARNING
        # Task overdue but no immediate attention is required
        return IssueSeverity.INFO

    @staticmethod
    def _format_overdue_description(task_config: TaskConfig, days_overdue: int) -> str:
        """
        Format a human-readable description for an overdue task.

        Produces grammatically-correct text distinguishing "due today", singular ("1 day"),
        and plural ("N days") cases.

        Args:
            task_config (TaskConfig): Configuration of the overdue task (its `name` is included in
                the description).
            days_overdue (int): Number of days the task is overdue (0 = due today).

        Returns:
            str: Formatted description, e.g. ``"Task `failed-services` is overdue by 3 days"``.

        Examples:
            >>> from types import SimpleNamespace
            >>> cfg = SimpleNamespace(name="backup")
            >>> MaintenanceCheckTask._format_overdue_description(cfg, 0)
            'Task `backup` is due today'
            >>> MaintenanceCheckTask._format_overdue_description(cfg, 1)
            'Task `backup` is overdue by 1 day'
            >>> MaintenanceCheckTask._format_overdue_description(cfg, 5)
            'Task `backup` is overdue by 5 days'
        """
        if days_overdue == 0:
            return f"Task `{task_config.name}` is due today"
        if days_overdue == 1:
            return f"Task `{task_config.name}` is overdue by 1 day"
        return f"Task `{task_config.name}` is overdue by {days_overdue} days"

    @staticmethod
    def _format_time_ago(timestamp: datetime | None) -> str:
        """
        Format a timestamp as a human-readable "time ago" string.

        Chooses the largest non-zero unit (days → hours → minutes); sub-minute deltas render as
        "just now".

        Args:
            timestamp (datetime | None): Timestamp to format relative to now, or `None` for "never".

        Returns:
            str: Human-readable string such as `"2 days ago"`, `"1 hour ago"`, `"3 minutes ago"`,
                `"just now"`, or `"never"` if `timestamp` is `None`.

        Examples:
            >>> MaintenanceCheckTask._format_time_ago(None)
            'never'
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
        Post-execution actions: send desktop notification and save report file.

        Runs after `execute()` regardless of outcome. Two optional side effects are triggered based
        on [`MaintenanceCheckSettings`][archcare.config.models.MaintenanceCheckSettings]:

        - A desktop notification when `show_notifications` is enabled (further filtered by
            `notification_level`, see `self._send_notification` in the source code).
        - A timestamped text report written when `output_mode` is `"file"` or `"both"` (see
            `self._save_report` in the source code).

        Args:
            result (TaskResult[MaintenanceCheckDetails]): The result produced by `execute()`.

        Raises:
            ValueError: If `result.details` is unexpectedly `None` (defensive check; `execute()`
                always populates details).
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

    def _send_notification(self, details: MaintenanceCheckDetails) -> None:
        """
        Send a desktop notification based on check results.

        Determines the highest severity present in the findings and compares it against the
        configured `notification_level` (info=0, warning=1, critical=2): a notification is sent only
        when the finding severity meets or exceeds the configured threshold. No notification is sent
        when there are no findings at all.

        Args:
            details (MaintenanceCheckDetails): Check results containing the categorized issue lists
                and summary.

        Raises:
            ValueError: If the summary reports issues but all severity lists are empty (defensive
                check; should never happen).

        Side Effects:
            - Emits Loguru log messages at `debug` level when suppressed.
            - Sends a desktop notification via `NotificationManager.send_maintenance_notification`
                when the threshold is met and a notification manager is available.
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
    ) -> None:
        """
        Save a maintenance check report as a timestamped text file.

        Writes `maintenance-check_<YYYYMMDD_HHMMSS>.txt` into `self.settings.report_dir`. The report
        contains the status, the number of monitored tasks, a "tasks needing attention" list
        (critical + warning), and per-severity sections with formatted issue details. Afterwards,
        old reports are pruned via `self._cleanup_old_reports`.

        Args:
            details (MaintenanceCheckDetails): Check results to render into the report.
            timestamp (datetime): Report generation timestamp, used both in the filename and
                the header.
            status (TaskStatus): Overall status of the maintenance check.

        Side Effects:
            - Creates a new report file on disk.
            - May delete old report files past the retention window.
            - Emits Loguru log messages at `debug`/`info` levels.
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
            lines.extend(
                f"  - {maintenance_issue.task_name} ({str(maintenance_issue.severity).upper()})"
                for maintenance_issue in tasks_needing_attention
            )
            lines.append("\n")

        if not details.summary.has_issues:
            lines.append("✔ No maintenance issues found! Your system is healthy :)")
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
    ) -> None:
        """
        Append a titled issues section to the report lines.

        Writes the section header followed by an 80-character separator rule and one formatted block
        per issue (via `self._format_issue_text`).

        Args:
            lines (list[str]): Report lines being built; new lines are appended in place.
            header_title (str): Section header text (e.g., `"🟥 CRITICAL ISSUES"`).
            issues (list[MaintenanceIssue]): Issues to include in this section.

        Side Effects:
            Mutates `lines` by appending the section content.
        """
        lines.append(header_title)
        lines.append("-" * 80)
        for issue in issues:
            lines.extend(self._format_issue_text(issue))

    @staticmethod
    def _format_issue_text(issue: MaintenanceIssue) -> list[str]:
        """
        Format a single issue as report text lines.

        Emits the task name and description unconditionally, followed by days overdue, last run,
        and last status only when available, and always ends with the recommendation and a
        blank line.

        Args:
            issue (MaintenanceIssue): Issue to format.

        Returns:
            list[str]: Text lines for the report, including a trailing blank line.
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

    def _cleanup_old_reports(self) -> None:
        """
        Delete old maintenance reports according to the retention setting.

        Scans `self.settings.report_dir` for `maintenance-check_*.txt` files and removes any whose
        modification time is older than `report_retention_days` (default 30). Individual deletion
        failures are logged as warnings and do not abort the sweep.

        Side Effects:
            - Deletes expired report files from disk.
            - Emits Loguru log messages at `debug`/`info`/`warning` levels.
        """
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
