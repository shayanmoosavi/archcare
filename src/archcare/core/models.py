"""
Task result models for archcare.

Defines the return types and status tracking for task execution.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from archcare.config.models import TaskStatus


@dataclass
class TaskResult:
    """
    Result of a task execution.

    This is returned by every task's execute() method to provide
    detailed information about what happened during execution.
    """

    status: TaskStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    error: Exception | None = None
    timestamp: datetime = field(default_factory=datetime.now)
    duration_seconds: float = 0.0

    def is_success(self) -> bool:
        """Check if task succeeded."""
        return self.status == TaskStatus.SUCCESS

    def is_failed(self) -> bool:
        """Check if task failed."""
        return self.status == TaskStatus.FAILURE

    def is_skipped(self) -> bool:
        """Check if task was skipped."""
        return self.status == TaskStatus.SKIPPED

    def is_partial(self) -> bool:
        """Check if task partially succeeded."""
        return self.status == TaskStatus.PARTIAL

    def __str__(self) -> str:
        """Human-readable representation."""
        parts = [f"[{self.status.value.upper()}] {self.message}"]

        if self.duration_seconds > 0:
            parts.append(f"({self.duration_seconds:.2f}s)")

        if self.error:
            parts.append(f"Error: {str(self.error)}")

        return " ".join(parts)


@dataclass
class TaskStep:
    """
    Represents a single step within a task execution.

    Tasks can report progress by yielding TaskStep objects during execution.
    This allows for real-time progress updates in the CLI.
    """

    name: str
    status: TaskStatus
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        """Human-readable representation."""
        if self.message:
            return f"{self.name}: {self.message}"
        return self.name


def success(message: str, **details) -> TaskResult:
    """
    Create a success result.

    Args:
        message: Success message
        **details: Additional details to include

    Returns:
        TaskResult with SUCCESS status
    """
    return TaskResult(status=TaskStatus.SUCCESS, message=message, details=details)


def failed(message: str, error: Exception | None = None, **details) -> TaskResult:
    """
    Create a failure result.

    Args:
        message: Failure message
        error: Exception that caused the failure (optional)
        **details: Additional details to include

    Returns:
        TaskResult with FAILED status
    """
    return TaskResult(
        status=TaskStatus.FAILURE, message=message, error=error, details=details
    )


def skipped(message: str, **details) -> TaskResult:
    """
    Create a skipped result.

    Args:
        message: Reason for skipping
        **details: Additional details to include

    Returns:
        TaskResult with SKIPPED status
    """
    return TaskResult(status=TaskStatus.SKIPPED, message=message, details=details)


def partial(message: str, **details) -> TaskResult:
    """
    Create a partial result.

    Args:
        message: Current status message
        **details: Additional details to include

    Returns:
        TaskResult with PARTIAL status
    """
    return TaskResult(status=TaskStatus.PARTIAL, message=message, details=details)
