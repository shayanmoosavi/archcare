"""
Task detail formatters.

Implements the Factory Pattern to isolate domain-specific terminal output
formatting from the Presenter layer.
"""

from abc import ABC, abstractmethod
from typing import Any


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
