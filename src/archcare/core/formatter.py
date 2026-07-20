"""Formatter port for the Archcare core layer."""

import dataclasses
from typing import Any, Protocol


class TaskDetailFormatter(Protocol):
    """Port through which the presentation layer renders a task's execution details."""

    def format(self, details: Any) -> list[str]:
        """Convert a task's details dictionary into formatted output lines."""
        ...


class DefaultFormatter:
    """
    Default formatter used when a task has no dedicated formatter
    registered. Falls back to a generic field dump for any dataclass, or
    a bare string representation for anything else.
    """

    def format(self, details: Any) -> list[str]:
        if details is None:
            return []
        if dataclasses.is_dataclass(details):
            return [
                f"  {f.name}: {getattr(details, f.name)}"
                for f in dataclasses.fields(details)
                if not f.name.startswith("_")
            ]
        return [f"  {details}"]
