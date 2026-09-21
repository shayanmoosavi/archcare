"""
Task detail formatters.

Concrete implementations of the
[`TaskDetailFormatter`][archcare.core.formatter.TaskDetailFormatter] port, each rendering one task's
execution details as Rich-markup terminal output. Routing from task name to formatter class lives in
[`TaskRegistry`][archcare.core.task_registry.TaskRegistry], not here — this module only supplies the
CLI-specific rendering for each domain.

Each formatter returns a list of Rich-markup strings, which are appended to the task result panel by
[`TaskPresenter`][archcare.cli.presenters.task_presenter.TaskPresenter] in verbose mode.

Formatters provided:

- [`FailedServicesFormatter`][]: failed systemd units, with log excerpts
- [`HealthCheckFormatter`][]: health issues plus system resource summary
- [`MirrorlistUpdateFormatter`][]: mirror count changes, backup path, previous update time
- [`MaintenanceCheckFormatter`][]: tasks needing attention plus schedule summary

See Also:
    - [`archcare.core.formatter`][]: The port (protocol) these implement
    - [`TaskRegistry`][archcare.core.task_registry.TaskRegistry]: Name → formatter routing
"""

from archcare.core import (
    FailedServiceInfo,
    FailedServicesDetails,
    HealthCheckDetails,
    HealthCheckSummary,
    IssueSeverity,
    MaintenanceCheckDetails,
    MaintenanceCheckSummary,
    MirrorlistUpdateDetails,
)


class FailedServicesFormatter:
    """
    Formats details for the `failed-services` task.

    Renders the failure counts (total, requiring attention, ignored) and — when any non-ignored
    failures exist — a detailed listing of each failed service with description, status, and the
    last few journal log lines.

    See also:
        - [`TaskRegistry`][archcare.core.task_registry.TaskRegistry]: The place where the formatters
            get registered
        - [`render_run`][archcare.cli.presenters.task_presenter.TaskPresenter.render_run]: The
            method which uses this presenter
        - [`FailedServicesTask`][archcare.tasks.failed_services.FailedServicesTask]: The task that
            this formatter renders the details for
    """

    def format(self, details: FailedServicesDetails) -> list[str]:
        """
        Render `failed-services` task details as Rich-markup lines.

        Args:
            details (FailedServicesDetails): Counts and per-service failure info from the
                `failed-services` run.

        Returns:
            (list[str]): Rich-markup lines summarizing the failure counts and, when present, each
                failing service (with status and recent log excerpts, truncated to 160 chars,
                last 3 lines).
        """
        lines = []

        lines.append(f"[blue]  Total failed: {details.total_failed}[/blue]")
        lines.append(f"[red]   Requiring attention: {details.actual_failures}[/red]")
        lines.append(f"[dim]  Ignored: {details.ignored}[/dim]")

        if details.failed_services:
            lines.append("\n[bold]Failed Services:[/bold]")

            self._add_failure_details(details.failed_services, lines)

        return lines

    @staticmethod
    def _add_failure_details(failed_services: list[FailedServiceInfo], lines: list[str]):
        """
        Append detailed failed services information to lines.

        For each failure: the unit name (red), its description (when present), its active state,
        and up to the last 3 journal log lines with each line truncated to 160 characters.

        Args:
            failed_services (list[FailedServiceInfo]): Failed units to detail, in list order.
            lines (list[str]): Accumulator list the markup lines are appended to.
        """
        for failure in failed_services:
            lines.append(f"  • [red]{failure.service}[/red]")
            if desc := failure.description:
                lines.append(f"    {desc}")
            lines.append(f"    Status: {failure.active}")

            # Show a few log lines
            if logs := failure.logs:
                lines.append("    Recent logs:")
                for log in logs[-3:]:  # Last 3 lines
                    lines.append(f"      {log[:160]}")  # Truncate long lines


class HealthCheckFormatter:
    """
    Formats details for the `health-check` task.

    Renders health issues and warnings as bulleted lists (red/yellow respectively), followed by a
    system summary: color-coded resource usage (disk/memory/CPU), filesystem error count, pacman
    database and installed package health, and system uptime.

    See also:
        - [`TaskRegistry`][archcare.core.task_registry.TaskRegistry]: The place where the formatters
            get registered
        - [`render_run`][archcare.cli.presenters.task_presenter.TaskPresenter.render_run]: The
            method which uses this presenter
        - [`HealthCheckTask`][archcare.tasks.health_check.HealthCheckTask]: The task that this
            formatter renders the details for
    """

    def format(self, details: HealthCheckDetails) -> list[str]:
        """
        Render `health-check` task details as Rich-markup lines.

        Args:
            details (HealthCheckDetails): Issues/warnings lists plus the [`HealthCheckSummary`][]
                from the health-check run.

        Returns:
            (list[str]): Rich-markup lines with the critical issues section (when present), warnings
                section (when present), and the system summary.
        """
        lines = []

        if issues := details.issues:
            lines.append("\n[bold red]Critical Issues:[/bold red]")
            for issue in issues:
                lines.append(f"  • {issue}")

        if warnings := details.warnings:
            lines.append("\n[bold yellow]Warnings:[/bold yellow]")
            for warning in warnings:
                lines.append(f"  • {warning}")

        # Show summary statistics
        summary = details.summary
        self._format_summary(lines, summary)

        return lines

    @staticmethod
    def _format_summary(lines: list[str], summary: HealthCheckSummary):
        """
        Append the system health summary to lines.

        Resource usage percentages are color-coded by threshold: disk and memory turn yellow above
        80% and red above 90%; CPU turns yellow above 90%. Filesystem errors are shown in red when
        non-zero; the pacman database and installed package files are reported as `Healthy` (green)
        or `Issues Detected` (red).

        Args:
            lines (list[str]): Accumulator list the markup lines are appended to.
            summary (HealthCheckSummary): Aggregated health metrics to render.
        """
        lines.append("\n[bold]System Summary:[/bold]")

        # Format resource usage metrics
        for usage, pct, thresholds in [
            ("Disk Usage", summary.disk_usage_percent, [(90, "red"), (80, "yellow")]),
            (
                "Memory Usage",
                summary.memory_usage_percent,
                [(90, "red"), (80, "yellow")],
            ),
            ("CPU Usage", summary.cpu_usage_percent, [(90, "yellow")]),
        ]:
            color = next((color for threshold, color in thresholds if pct > threshold), "green")
            lines.append(f"  {usage}: [{color}]{pct:.1f}%[/{color}]")

        # Filesystem errors
        if summary.filesystem_errors_count > 0:
            lines.append(f"  Filesystem Errors: [red]{summary.filesystem_errors_count}[/red]")

        # Pacman and package status
        for label, healthy in [
            ("Pacman Database", summary.pacman_healthy),
            ("Installed Package Files", summary.packages_healthy),
        ]:
            status = "[green]Healthy[/green]" if healthy else "[red]Issues Detected[/red]"
            lines.append(f"  {label}: {status}")

        # Uptime
        lines.append(f"  System Uptime: {summary.uptime}")


class MirrorlistUpdateFormatter:
    """
    Formats details for the `mirrorlist-update` task.

    Renders the mirror count change (old → new), the backup file path, and the previous update
    timestamp. Fields absent from the run (e.g., no backup taken) are simply omitted from
    the output.

    See also:
        - [`TaskRegistry`][archcare.core.task_registry.TaskRegistry]: The place where the formatters
            get registered
        - [`render_run`][archcare.cli.presenters.task_presenter.TaskPresenter.render_run]: The
            method which uses this presenter
        - [`MirrorlistUpdateTask`][archcare.tasks.mirrorlist_update.MirrorlistUpdateTask]: The task
            that this formatter renders the details for
    """

    def format(self, details: MirrorlistUpdateDetails) -> list[str]:
        """
        Render `mirrorlist-update` task details as Rich-markup lines.

        Args:
            details (MirrorlistUpdateDetails): Mirror counts, backup path, and previous file info
                from the mirrorlist-update run.

        Returns:
            (list[str]): Rich-markup lines, one per available datum: the mirror count transition,
                the backup location, and the previous update time. Empty when nothing changed.
        """
        lines = []

        if details.old_mirrors is not None and details.new_mirrors is not None:
            lines.append(f"  Mirrors: {details.old_mirrors} → {details.new_mirrors}")

        if details.backup_path:
            lines.append(f"  Backup: {details.backup_path}")

        if last_modified := details.old_info.last_modified:
            lines.append(f"  Previous update: {last_modified}")

        return lines


class MaintenanceCheckFormatter:
    """
    Formats details for the `maintenance-check` task.

    Renders the tasks needing attention (with severity badges: red `❗ CRITICAL` or yellow
    ` WARNING`) followed by a schedule summary (total monitored tasks and counts by severity).
    This is a compact textual alternative to the full report rendered by
    [`MaintenanceCheckPresenter`][archcare.cli.presenters.maintenance_presenter.MaintenanceCheckPresenter].

    See also:
        - [`TaskRegistry`][archcare.core.task_registry.TaskRegistry]: The place where the formatters
            get registered
        - [`render_run`][archcare.cli.presenters.task_presenter.TaskPresenter.render_run]: The
            method which uses this presenter
        - [`MaintenanceCheckTask`][archcare.tasks.maintenance_check.MaintenanceCheckTask]: The task
            that this formatter renders the details for
    """

    def format(self, details: MaintenanceCheckDetails) -> list[str]:
        """
        Render `maintenance-check` details as Rich-markup lines.

        Args:
            details (MaintenanceCheckDetails): Tasks needing attention plus the
                [`MaintenanceCheckSummary`][] from the maintenance-check run.

        Returns:
            (list[str]): Rich-markup lines with the "Tasks needing attention" section (when present)
                and the summary counts.
        """
        lines = []

        if tasks_needing_attention := details.tasks_needing_attention:
            severity_mapping = {
                IssueSeverity.CRITICAL: "[red]❗ CRITICAL[/red]",
                IssueSeverity.WARNING: "[yellow] WARNING[/yellow]",
            }
            lines.append("[bold]Tasks needing attention: [/bold]")
            for issue in tasks_needing_attention:
                lines.append(f"[blue]  • {issue.task_name}[/blue]")
                lines.append(f"    ▶ {severity_mapping[issue.severity]}")

        # Show summary statistics
        summary = details.summary
        self._format_summary(lines, summary)

        return lines

    @staticmethod
    def _format_summary(lines: list[str], summary: MaintenanceCheckSummary):
        """
        Append the maintenance schedule summary to lines.

        Args:
            lines (list[str]): Accumulator list the markup lines are appended to.
            summary (MaintenanceCheckSummary): Aggregated schedule counts to render: total monitored
                tasks and critical/warning/info issue counts.
        """
        lines.extend(
            [
                "\n[bold]Summary: [/bold]",
                f"  Total tasks monitored: {summary.total_tasks_monitored}",
                f"  Critical issues: {summary.critical_count}",
                f"  Warning issues: {summary.warning_count}",
                f"  Informational issues: {summary.info_count}\n",
            ]
        )
