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


class HealthCheckFormatter:
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
        lines.append("\n[bold]System Summary:[/bold]")

        # Disk
        disk_pct = summary.get("disk_usage_percent", 0)
        disk_color = "red" if disk_pct > 90 else "yellow" if disk_pct > 80 else "green"
        lines.append(f"  Disk Usage: [{disk_color}]{disk_pct:.1f}%[/{disk_color}]")

        # Memory
        mem_pct = summary.get("memory_usage_percent", 0)
        mem_color = "red" if mem_pct > 90 else "yellow" if mem_pct > 80 else "green"
        lines.append(f"  Memory Usage: [{mem_color}]{mem_pct:.1f}%[/{mem_color}]")

        # CPU
        cpu_pct = summary.get("cpu_usage_percent", 0)
        cpu_color = "yellow" if cpu_pct > 90 else "green"
        lines.append(f"  CPU Usage: [{cpu_color}]{cpu_pct:.1f}%[/{cpu_color}]")

        # Filesystem errors
        fs_errors = summary.get("filesystem_errors_count", 0)
        if fs_errors > 0:
            lines.append(f"  Filesystem Errors: [red]{fs_errors}[/red]")

        # Pacman
        pacman_ok = summary.get("pacman_healthy", False)
        pacman_status = (
            "[green]Healthy[/green]" if pacman_ok else "[red]Issues Detected[/red]"
        )
        lines.append(f"  Pacman Database: {pacman_status}")

        packages_ok = summary.get("packages_healthy", False)
        packages_status = (
            "[green]Healthy[/green]" if packages_ok else "[red]Issues Detected[/red]"
        )
        lines.append(f"  Installed Package Files: {packages_status}")

        # Uptime
        uptime = summary.get("uptime", "unknown")
        lines.append(f"  System Uptime: {uptime}")

        return lines


class MaintenanceCheckFormatter:
    """Formats details for the maintenance-check task."""

    def format(self, details: dict[str, Any]) -> list[str]:
        lines = []
        lines.append("\n[bold]Summary: [/bold]")

        # Summary statistics
        lines.append(
            f"  Total tasks monitored: {details.get('total_tasks_monitored', -1)}"
        )
        lines.append(f"  Critical issues: {details.get('critical_count', -1)}")
        lines.append(f"  Warning issues: {details.get('warning_count', -1)}")
        lines.append(f"  Informational issues: {details.get('info_count', -1)}\n")

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
