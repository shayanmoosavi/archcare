"""
Task result models for archcare.

Defines the return types and status tracking for task execution.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from archcare.config.models import SkipReason, TaskStatus


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
    skip_reason: SkipReason | None = None
    skip_message: str | None = None
    error_message: str | None = None

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


class IssueSeverity(Enum):
    """Severity levels for maintenance issues."""

    CRITICAL = "critical"  # Requires immediate attention
    WARNING = "warning"  # Should be addressed soon
    INFO = "info"  # Informational, no action needed immediately

    def __str__(self) -> str:
        return self.value


class MaintenanceIssue(BaseModel):
    """Represents a single maintenance issue found during check."""

    task_name: str = Field(..., description="Name of the task with issue")
    severity: IssueSeverity = Field(..., description="Severity of the issue")
    description: str = Field(..., description="Human-readable description")
    days_overdue: int | None = Field(
        None, description="Days overdue (negative if not yet due)"
    )
    last_run: datetime | None = Field(None, description="Last execution time")
    last_status: TaskStatus | None = Field(None, description="Last execution status")
    recommendation: str = Field(..., description="Actionable recommendation")

    @property
    def is_overdue(self) -> bool:
        """Check if task is overdue."""
        return self.days_overdue is not None and self.days_overdue > 0

    @property
    def severity_emoji(self) -> str:
        """Get emoji for severity level."""
        return {
            IssueSeverity.CRITICAL: "🟥",
            IssueSeverity.WARNING: "🟨",
            IssueSeverity.INFO: "🟦",
        }[self.severity]


class MaintenanceCheckResult(BaseModel):
    """Result of maintenance check task execution."""

    task_name: str = Field(default="maintenance-check", description="Task name")
    status: TaskStatus = Field(..., description="Overall check status")
    timestamp: datetime = Field(
        default_factory=datetime.now, description="When check was performed"
    )

    # Issues categorized by severity
    critical_issues: list[MaintenanceIssue] = Field(
        default_factory=list,
        description="Critical issues requiring immediate attention",
    )
    warning_issues: list[MaintenanceIssue] = Field(
        default_factory=list, description="Warning issues that should be addressed"
    )
    info_issues: list[MaintenanceIssue] = Field(
        default_factory=list, description="Informational issues"
    )

    # Summary statistics
    total_tasks_monitored: int = Field(
        default=0, description="Total number of tasks checked"
    )
    error_message: str | None = Field(None, description="Error message if check failed")

    @property
    def all_issues(self) -> list[MaintenanceIssue]:
        """Get all issues sorted by severity."""
        return self.critical_issues + self.warning_issues + self.info_issues

    @property
    def tasks_needing_attention(self) -> list[MaintenanceIssue]:
        """Get all important issues sorted by severity"""
        return self.critical_issues + self.warning_issues

    @property
    def has_issues(self) -> bool:
        """Check if there are any issues at all."""
        return len(self.tasks_needing_attention) > 0

    @property
    def summary_message(self) -> str:
        """Generate a summary message."""
        if not self.has_issues:
            return "✓ All maintenance tasks are up to date!"

        parts = []
        if self.critical_issues:
            parts.append(f"{len(self.critical_issues)} critical")
        if self.warning_issues:
            parts.append(f"{len(self.warning_issues)} warning")
        if self.info_issues:
            parts.append(f"{len(self.info_issues)} info")

        return f"Found {', '.join(parts)} issue(s) requiring attention"

    def get_issues_by_severity(self, severity: IssueSeverity) -> list[MaintenanceIssue]:
        """Get issues filtered by severity level."""
        severity_map = {
            IssueSeverity.CRITICAL: self.critical_issues,
            IssueSeverity.WARNING: self.warning_issues,
            IssueSeverity.INFO: self.info_issues,
        }
        return severity_map[severity]

    def to_task_result(self) -> TaskResult:
        """Convert to standard TaskResult format."""
        return TaskResult(
            status=self.status,
            message=self.summary_message,
            details={
                "total_tasks_monitored": self.total_tasks_monitored,
                "tasks_needing_attention": self.tasks_needing_attention,
                "critical_count": len(self.critical_issues),
                "warning_count": len(self.warning_issues),
                "info_count": len(self.info_issues),
            },
            error_message=self.error_message,
        )


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


def skipped(message: str, skip_reason: SkipReason | None, **details) -> TaskResult:
    """
    Create a skipped result.

    Args:
        message: Message for skipping
        skip_reason: SkipReason enum for skipping
        **details: Additional details to include

    Returns:
        TaskResult with SKIPPED status
    """
    return TaskResult(
        status=TaskStatus.SKIPPED,
        message=message,
        skip_reason=skip_reason,
        skip_message=message,
        details=details,
    )


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
