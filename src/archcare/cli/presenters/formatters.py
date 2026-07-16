"""
Task detail formatters.

Implements the Factory Pattern to isolate domain-specific terminal output
formatting from the Presenter layer.
"""

from abc import ABC, abstractmethod
from typing import Any

from archcare.core import MaintenanceIssue


class TaskDetailFormatter(ABC):
    """Base class for task-specific detail formatters."""

    @abstractmethod
    def format(self, details: dict[str, Any]) -> list[str]:
        """Convert a task's details dictionary into a list of formatted Rich strings."""
        pass


class DefaultFormatter(TaskDetailFormatter):
    """Fallback formatter for generic tasks."""

    def format(self, details: dict[str, Any]) -> list[str]:
        lines = []
        for key, value in details.items():
            if not key.startswith("_"):  # Skip internal keys
                lines.append(f"  {key}: {value}")
        return lines


class FailedServicesFormatter(TaskDetailFormatter):
    """Formats details for the failed-services task."""

    def format(self, details: dict[str, Any]) -> list[str]:
        lines = []

        failed_services = details.get("failed_services", [])
        total = details.get("total_failed", 0)
        actual = details.get("actual_failures", 0)
        ignored = details.get("ignored", 0)

        lines.append(f"[blue]  Total failed: {total}[/blue]")
        lines.append(f"[red]  ⚠ Requiring attention: {actual}[/red]")
        lines.append(f"[dim]  Ignored: {ignored}[/dim]")

        if failed_services:
            lines.append("\n[bold]Failed Services:[/bold]")

            self._add_failure_details(failed_services, lines)

        return lines

    @staticmethod
    def _add_failure_details(failed_services: list[dict[str, Any]], lines: list[str]):
        """Add detailed failed services information to lines."""
        for failure in failed_services:
            service = failure.get("service", "unknown")
            desc = failure.get("description", "")
            active = failure.get("active", "unknown")

            lines.append(f"  • [red]{service}[/red]")
            if desc:
                lines.append(f"    {desc}")
            lines.append(f"    Status: {active}")

            # Show a few log lines
            logs = failure.get("logs", [])
            if logs:
                lines.append("    Recent logs:")
                for log in logs[-3:]:  # Last 3 lines
                    lines.append(f"      {log[:160]}")  # Truncate long lines


class HealthCheckFormatter(TaskDetailFormatter):
    """Formats details for the health-check task."""

    def format(self, details: dict[str, Any]) -> list[str]:
        lines = []
        issues = details.get("issues", [])
        warnings = details.get("warnings", [])
        summary = details.get("summary", {})

        if issues:
            lines.append("\n[bold red]Critical Issues:[/bold red]")
            for issue in issues:
                lines.append(f"  • {issue}")

        if warnings:
            lines.append("\n[bold yellow]Warnings:[/bold yellow]")
            for warning in warnings:
                lines.append(f"  • {warning}")

        # Show summary statistics
        self._format_summary(lines, summary)

        return lines

    @staticmethod
    def _format_summary(lines: list[Any], summary):
        lines.append("\n[bold]System Summary:[/bold]")

        # Format resource usage metrics
        for usage, key, thresholds in [
            ("Disk Usage", "disk_usage_percent", [(90, "red"), (80, "yellow")]),
            ("Memory Usage", "memory_usage_percent", [(90, "red"), (80, "yellow")]),
            ("CPU Usage", "cpu_usage_percent", [(90, "yellow")]),
        ]:
            pct = summary.get(key, 0)
            color = next(
                (color for threshold, color in thresholds if pct > threshold), "green"
            )
            lines.append(f"  {usage}: [{color}]{pct:.1f}%[/{color}]")

        # Filesystem errors
        if (fs_errors := summary.get("filesystem_errors_count", 0)) > 0:
            lines.append(f"  Filesystem Errors: [red]{fs_errors}[/red]")

        # Pacman and package status
        for label, key in [
            ("Pacman Database", "pacman_healthy"),
            ("Installed Package Files", "packages_healthy"),
        ]:
            status = (
                "[green]Healthy[/green]"
                if summary.get(key, False)
                else "[red]Issues Detected[/red]"
            )
            lines.append(f"  {label}: {status}")

        # Uptime
        lines.append(f"  System Uptime: {summary.get("uptime", "unknown")}")


class MaintenanceCheckFormatter(TaskDetailFormatter):
    """Formats details for the maintenance-check task."""

    def format(self, details: dict[str, Any]) -> list[str]:
        lines = [
            "\n[bold]Summary: [/bold]",
            f"  Total tasks monitored: {details.get('total_tasks_monitored', -1)}",
            f"  Critical issues: {details.get('critical_count', -1)}",
            f"  Warning issues: {details.get('warning_count', -1)}",
            f"  Informational issues: {details.get('info_count', -1)}\n",
        ]

        # Summary statistics

        tasks_needing_attention: list[MaintenanceIssue] = details.get(
            "tasks_needing_attention", []
        )
        if tasks_needing_attention:
            severity_mapping = {
                "critical": "[red]❗ CRITICAL[/red]",
                "warning": "[yellow]⚠ WARNING[/yellow]",
                "info": "[blue]ℹ INFO[/blue]",
            }
            lines.append("[bold]Tasks needing attention: [/bold]")
            for issue in tasks_needing_attention:
                lines.append(f"[blue]  • {issue.task_name}[/blue]")
                # Safely get severity name string if it's an Enum
                sev_key = str(issue.severity)
                lines.append(f"    ‒ {severity_mapping[sev_key]}")

        return lines


class FormatterFactory:
    """Routes task names to their specific terminal formatters."""

    _REGISTRY: dict[str, type[TaskDetailFormatter]] = {
        "failed-services": FailedServicesFormatter,
        "health-check": HealthCheckFormatter,
        "maintenance-check": MaintenanceCheckFormatter,
    }

    @classmethod
    def get_formatter(cls, task_name: str) -> TaskDetailFormatter:
        """Returns the specific formatter, or DefaultFormatter if none is registered."""
        formatter = cls._REGISTRY.get(task_name, DefaultFormatter)
        return formatter()
