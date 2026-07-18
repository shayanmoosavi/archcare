"""Formatter port for the Archcare core layer."""

from typing import Any, Protocol


class TaskDetailFormatter(Protocol):
    """Port through which the presentation layer renders a task's execution details."""

    def format(self, details: dict[str, Any]) -> list[str]:
        """Convert a task's details dictionary into formatted output lines."""
        ...


class DefaultFormatter:
    """
    Default formatter used when a task has no dedicated formatter
    registered (fallback for tests, unregistered tasks, or any caller
    that doesn't need domain-specific rendering).
    """

    def format(self, details: dict[str, Any]) -> list[str]:
        lines = []
        for key, value in details.items():
            if not key.startswith("_"):  # Skip internal keys
                lines.append(f"  {key}: {value}")
        return lines
