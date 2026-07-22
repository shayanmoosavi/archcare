"""
Task detail formatters.

Concrete implementations of the archcare.core.formatter.TaskDetailFormatter
port, each rendering one task's execution details as Rich-markup terminal
output. Routing from task name to formatter class lives in
core.task_registry.TaskRegistry, not here - this module only supplies the
CLI-specific rendering for each domain.
"""

from archcare.core import (
    FailedServiceInfo,
    FailedServicesDetails,
    HealthCheckDetails,
    HealthCheckSummary,
    MaintenanceCheckDetails,
    MaintenanceCheckSummary,
    MirrorlistUpdateDetails,
)


class FailedServicesFormatter:
    """Formats details for the failed-services task."""

    def format(self, details: FailedServicesDetails) -> list[str]:
        lines = []

        lines.append(f"[blue]  Total failed: {details.total_failed}[/blue]")
        lines.append(f"[red]  ⚠ Requiring attention: {details.actual_failures}[/red]")
        lines.append(f"[dim]  Ignored: {details.ignored}[/dim]")

        if details.failed_services:
            lines.append("\n[bold]Failed Services:[/bold]")

            self._add_failure_details(details.failed_services, lines)

        return lines

    @staticmethod
    def _add_failure_details(
        failed_services: list[FailedServiceInfo], lines: list[str]
    ):
        """Add detailed failed services information to lines."""
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
    """Formats details for the health-check task."""

    def format(self, details: HealthCheckDetails) -> list[str]:
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
            color = next(
                (color for threshold, color in thresholds if pct > threshold), "green"
            )
            lines.append(f"  {usage}: [{color}]{pct:.1f}%[/{color}]")

        # Filesystem errors
        if summary.filesystem_errors_count > 0:
            lines.append(
                f"  Filesystem Errors: [red]{summary.filesystem_errors_count}[/red]"
            )

        # Pacman and package status
        for label, healthy in [
            ("Pacman Database", summary.pacman_healthy),
            ("Installed Package Files", summary.packages_healthy),
        ]:
            status = (
                "[green]Healthy[/green]" if healthy else "[red]Issues Detected[/red]"
            )
            lines.append(f"  {label}: {status}")

        # Uptime
        lines.append(f"  System Uptime: {summary.uptime}")


class MirrorlistUpdateFormatter:
    """Formats details for the mirrorlist-update task."""

    def format(self, details: MirrorlistUpdateDetails) -> list[str]:
        lines = []

        if details.old_mirrors is not None and details.new_mirrors is not None:
            lines.append(f"  Mirrors: {details.old_mirrors} → {details.new_mirrors}")

        if details.backup_path:
            lines.append(f"  Backup: {details.backup_path}")

        if last_modified := details.old_info.get("last_modified"):
            lines.append(f"  Previous update: {last_modified}")

        return lines


class MaintenanceCheckFormatter:
    """Formats details for the maintenance-check task."""

    def format(self, details: MaintenanceCheckDetails) -> list[str]:

        lines = []

        if tasks_needing_attention := details.tasks_needing_attention:
            severity_mapping = {
                "critical": "[red]❗ CRITICAL[/red]",
                "warning": "[yellow]⚠ WARNING[/yellow]",
            }
            lines.append("[bold]Tasks needing attention: [/bold]")
            for issue in tasks_needing_attention:
                lines.append(f"[blue]  • {issue.task_name}[/blue]")
                # Safely get severity name string if it's an Enum
                sev_key = str(issue.severity)
                lines.append(f"    ‒ {severity_mapping[sev_key]}")

        # Show summary statistics
        summary = details.summary
        self._format_summary(lines, summary)

        return lines

    @staticmethod
    def _format_summary(lines: list[str], summary: MaintenanceCheckSummary):
        lines.extend(
            [
                "\n[bold]Summary: [/bold]",
                f"  Total tasks monitored: {summary.total_tasks_monitored}",
                f"  Critical issues: {summary.critical_count}",
                f"  Warning issues: {summary.warning_count}",
                f"  Informational issues: {summary.info_count}\n",
            ]
        )
