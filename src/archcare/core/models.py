"""
Task result models and data structures for archcare core functionality.

This module provides comprehensive data models for representing task execution
results, progress tracking, and maintenance issue reporting in archcare. It
serves as the foundation for communicating task status and results throughout
the archcare application.

Module Overview:
    - TaskResult: Encapsulates complete results from task execution
    - TaskStep: Represents granular progress updates during task execution
    - IssueSeverity: Enum defining severity levels for maintenance issues
    - MaintenanceIssue: Data model for individual maintenance issues
    - Helper functions: Factory functions for creating TaskResult instances

Key Features:
    - Status tracking with multiple states (SUCCESS, FAILURE, SKIPPED, PARTIAL)
    - Detailed error tracking and exception handling
    - Real-time progress reporting through TaskStep objects
    - Maintenance issue classification by severity
    - Conversion utilities between different result formats

See Also:
    archcare.config.models: Task status enums and configuration data models
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from archcare.config import SkipReason, TaskStatus


@dataclass
class TaskResult[TDetails]:
    """
    Complete result of a task execution encapsulating status, messages, and metadata.

    This dataclass is returned by every task's execute() method and provides
    comprehensive information about what happened during execution. It combines
    status tracking, error information, timing data, and contextual details
    into a single, structured response object.

    The TaskResult supports multiple status states (SUCCESS, FAILURE, SKIPPED,
    PARTIAL) and provides convenience methods for checking status. Additional
    metadata including execution duration, skip reasons, and error messages
    provide detailed insights into task behavior.

    Attributes:
        status (TaskStatus): The final outcome of task execution. Can be one of:
            - SUCCESS: Task completed successfully
            - FAILURE: Task encountered an error and failed
            - SKIPPED: Task was skipped (not executed)
            - PARTIAL: Task partially completed (e.g., some checks passed)
        message (str): Human-readable description of the result. For success,
            typically describes what was accomplished. For failures, describes
            the error. For skipped tasks, describes why skipping occurred.
        details (TDetails | None): Optional structured data providing
            additional context about the execution - a typed dataclass
            specific to the task that produced it (see core.task_details),
            or None if there's nothing to report.
        error (str | None): The error message for the failure, defaults
            to None for successful or skipped tasks.
        timestamp (datetime): When the task execution completed. Automatically
            set to the current time when TaskResult is created. Used for
            audit trails and determining execution order.
        duration_seconds (float): How long the task took to execute, in seconds.
            Used for performance monitoring and optimization. Defaults to 0.0
            if not explicitly set.
        skip_reason (SkipReason | None): Enumerated reason why the task was
            skipped, if status is SKIPPED. Examples: DISABLED, DEPENDENCY_FAILED,
            NOT_DUE. Defaults to None.

    Methods:
        is_success() -> bool: Check if the task succeeded (status == SUCCESS).
        is_failed() -> bool: Check if the task failed (status == FAILURE).
        is_skipped() -> bool: Check if the task was skipped (status == SKIPPED).
        is_partial() -> bool: Check if the task partially succeeded (status == PARTIAL).
        __str__() -> str: Generate a human-readable string representation.

    Examples:
        >>> from archcare.config.models import TaskStatus
        >>> result = TaskResult(
        ...     status=TaskStatus.SUCCESS,
        ...     message="System updated successfully",
        ...     duration_seconds=12.5
        ... )
        >>> result.is_success()
        True
        >>> str(result)
        '[SUCCESS] System updated successfully (12.50s)'

        >>> # Create a failure result with exception
        >>> def risky_operation():
        ...     raise ValueError("Raising ValueError...")
        >>> try:
        ...     risky_operation()
        ... except Exception as e:
        ...     result = TaskResult(
        ...         status=TaskStatus.FAILURE,
        ...         message="Update check failed",
        ...         error=str(e),
        ...     )

    See Also:
        TaskStatus: Enumeration of possible task statuses
        SkipReason: Enumeration of reasons why a task might be skipped
        TaskStep: For reporting granular progress during execution
    """

    status: TaskStatus
    message: str
    details: TDetails | None = None
    error: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)
    duration_seconds: float = 0.0
    skip_reason: SkipReason | None = None

    def is_success(self) -> bool:
        """
        Check if the task completed successfully.

        Returns:
            bool: True if status is TaskStatus.SUCCESS, False otherwise.

        Examples:
            >>> result = TaskResult(status=TaskStatus.SUCCESS, message="OK")
            >>> result.is_success()
            True
        """
        return self.status == TaskStatus.SUCCESS

    def is_failed(self) -> bool:
        """
        Check if the task execution failed.

        Returns:
            bool: True if status is TaskStatus.FAILURE, False otherwise.

        Examples:
            >>> result = TaskResult(status=TaskStatus.FAILURE, message="Error occurred")
            >>> result.is_failed()
            True
        """
        return self.status == TaskStatus.FAILURE

    def is_skipped(self) -> bool:
        """
        Check if the task was skipped during execution.

        A task may be skipped if it was disabled, its dependencies failed,
        or preconditions were not met.

        Returns:
            bool: True if status is TaskStatus.SKIPPED, False otherwise.

        Examples:
            >>> result = TaskResult(
            ...     status=TaskStatus.SKIPPED,
            ...     message="Task disabled in configuration"
            ... )
            >>> result.is_skipped()
            True
        """
        return self.status == TaskStatus.SKIPPED

    def is_partial(self) -> bool:
        """
        Check if the task partially succeeded.

        A partial result indicates that the task made progress but did not
        fully complete or fully succeed. This is useful for operations where
        some checks pass while others fail.

        Returns:
            bool: True if status is TaskStatus.PARTIAL, False otherwise.

        Examples:
            >>> result = TaskResult(
            ...     status=TaskStatus.PARTIAL,
            ...     message="3 of 5 checks passed",
            ... )
            >>> result.is_partial()
            True
        """
        return self.status == TaskStatus.PARTIAL

    def __str__(self) -> str:
        """
        Generate a human-readable string representation of the result.

        The format includes the status in uppercase, the message, execution
        duration (if available), and error information (if applicable).

        Format:
            [STATUS] message (duration_seconds)
            [STATUS] message (duration_seconds) Error: error_details

        Returns:
            str: A formatted string representation suitable for logging or display.

        Examples:
            >>> result = TaskResult(
            ...     status=TaskStatus.SUCCESS,
            ...     message="Cleanup completed",
            ...     duration_seconds=5.23
            ... )
            >>> str(result)
            '[SUCCESS] Cleanup completed (5.23s)'

            >>> exc = RuntimeError("Disk full")
            >>> result = TaskResult(
            ...     status=TaskStatus.FAILURE,
            ...     message="Installation failed",
            ...     error=str(exc),
            ...     duration_seconds=2.1
            ... )
            >>> str(result)
            '[FAILURE] Installation failed (2.10s) Error: Disk full'
        """
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
    """
    Severity levels for maintenance issues.

    This enumeration classifies maintenance issues by their urgency and impact,
    helping users prioritize which issues to address first. All issues should
    be reviewed, but severity determines how quickly they need attention.

    Attributes:
        CRITICAL (str): Issues requiring immediate attention. These indicate
            problems that could impact system stability, security, or
            functionality. Example: Severely overdue maintenance tasks or broken
            systemd timers, typically by more than 1.5 times the frequency they
            should be performed. Should be addressed as soon as possible,
            typically within hours.
        WARNING (str): Issues that should be addressed soon. These indicate
            minor problems that don't immediately impact core functionality
            but may cause issues if left unattended. Example: Maintenance tasks
            overdue by a few days. Should be addressed within days.
        INFO (str): Informational issues with no immediate action needed.
            These are status updates or reminders for awareness only. Examples:
            Never-run maintenance tasks or tasks overdue by a day. Can be reviewed
            at user's convenience.

    Methods:
        __str__() -> str: Returns the string value of the enumeration.

    Examples:
        >>> severity = IssueSeverity.CRITICAL
        >>> str(severity)
        'critical'

        >>> for level in IssueSeverity:
        ...     print(f"Severity: {level.value}")
        Severity: critical
        Severity: warning
        Severity: info
    """

    CRITICAL = "critical"  # Requires immediate attention
    WARNING = "warning"  # Should be addressed soon
    INFO = "info"  # Informational, no action needed immediately

    def __str__(self) -> str:
        return self.value


@dataclass
class MaintenanceIssue:
    """
    Represents a single maintenance issue found during check.

    MaintenanceIssue encapsulates details about a specific maintenance problem
    discovered during system monitoring, providing comprehensive information for
    issue tracking, prioritization, and resolution.

    This model is used by maintenance-check task to report individual issues that
    require attention. Issues are categorized by severity (critical, warning, info)
    and include metadata about task execution history and actionable recommendations.

    Attributes:
        task_name (str): Name or identifier of the task associated with this issue.
            Examples: "system-update", "backup", "security-check". Used to identify
            which task has the problem and is required for all issues.
        severity (IssueSeverity): Severity classification determining urgency and
            priority. Must be one of: CRITICAL (immediate attention), WARNING (address
            soon), or INFO (awareness only). Required field that controls how the
            issue should be handled.
        description (str): Human-readable description of the issue providing context
            and details about what was found. Should be clear and specific enough for
            users to understand the problem without additional context. Examples:
            "System updates are 10 days overdue", "Backup failed with disk full error".
        days_overdue (int | None): Integer indicating how many days the task is
            overdue relative to its scheduled interval. Positive values indicate
            overdue tasks, negative values indicate tasks not yet due, and None
            indicates no due date tracking. Used to measure maintenance urgency.
            Defaults to None.
        last_run (datetime | None): Timestamp of the last time this task was
            executed successfully. Useful for determining when maintenance was
            last performed and calculating overdue periods. Defaults to None if
            task has never run.
        last_status (TaskStatus | None): Status result from the last task execution
            (SUCCESS, FAILURE, SKIPPED, PARTIAL). Provides execution history context
            to understand if the issue is a recurring problem or new event. Defaults
            to None if no execution history available.
        recommendation (str): Actionable recommendation for resolving this issue.
            Should be specific and executable. Examples: "Run system update immediately",
            "Check disk space and run cleanup", "Review and merge pacnew files".
            Required field that guides users toward resolution.

    Properties:
        is_overdue (bool): Check if the task is currently overdue based on
            days_overdue value.

    Examples:
        >>> # Critical issue requiring immediate attention
        >>> issue = MaintenanceIssue(
        ...     task_name="system-update",
        ...     severity=IssueSeverity.CRITICAL,
        ...     description="System updates are 10 days overdue",
        ...     days_overdue=10,
        ...     last_run=datetime(2025, 1, 1),
        ...     last_status=TaskStatus.FAILURE,
        ...     recommendation="Run system update immediately"
        ... )
        >>> issue.is_overdue
        True

        >>> # Warning issue that should be addressed
        >>> issue = MaintenanceIssue(
        ...     task_name="cache-cleanup",
        ...     severity=IssueSeverity.WARNING,
        ...     description="Cache hasn't been cleaned in 30 days",
        ...     days_overdue=5,
        ...     last_run=datetime(2025, 1, 20),
        ...     last_status=TaskStatus.SUCCESS,
        ...     recommendation="Run cache cleanup task"
        ... )

        >>> # Informational issue for tracking
        >>> issue = MaintenanceIssue(
        ...     task_name="health-check",
        ...     severity=IssueSeverity.INFO,
        ...     description="Disk usage at 65%",
        ...     days_overdue=None,
        ...     last_run=datetime.now(),
        ...     last_status=TaskStatus.SUCCESS,
        ...     recommendation="Monitor disk usage and plan for cleanup"
        ... )
    """

    task_name: str
    severity: IssueSeverity
    description: str
    recommendation: str
    days_overdue: int | None = None
    last_run: datetime | None = None
    last_status: TaskStatus | None = None

    @property
    def is_overdue(self) -> bool:
        """
        Check if task is overdue.

        A task is considered overdue if days_overdue is set to a positive value,
        indicating that the task hasn't run within its scheduled interval.

        Returns:
            bool: True if the task is overdue (days_overdue > 0), False otherwise
                  or if days_overdue is None.

        Examples:
            >>> # Overdue task
            >>> issue = MaintenanceIssue(
            ...     task_name="backup",
            ...     severity=IssueSeverity.WARNING,
            ...     description="Backup is overdue",
            ...     days_overdue=7,
            ...     recommendation="Run backup immediately"
            ... )
            >>> issue.is_overdue
            True

            >>> # Task not yet due
            >>> issue = MaintenanceIssue(
            ...     task_name="check",
            ...     severity=IssueSeverity.INFO,
            ...     description="Next check scheduled soon",
            ...     days_overdue=-3,  # Due in 3 days
            ...     recommendation="No action needed"
            ... )
            >>> issue.is_overdue
            False
        """
        return self.days_overdue is not None and self.days_overdue > 0


def success[TDetails](
    message: str, details: TDetails | None = None
) -> TaskResult[TDetails]:
    """
    Create a success result.

    A convenience factory function for creating a TaskResult with SUCCESS status.
    This is the standard way to report successful task completion.

    Args:
        message (str): Human-readable success message describing what was accomplished.
            Examples: "System updated successfully", "Cleanup completed",
             "All checks passed".
        details (TDetails | None): A dataclass instance describing task-specific structured
            details (see core.task_details for per-task schemas), or None
            if there's nothing to report.

    Returns:
        TaskResult[TDetails]: A new TaskResult instance with:
            - status: TaskStatus.SUCCESS
            - message: The provided message
            - details: The provided details instance
            - timestamp: Current time (set automatically)

    Examples:
        >>> from dataclasses import dataclass
        >>> @dataclass
        ... class UpdateDetails:
        ...     packages_updated: int
        ...     duration_ms: int
        >>> result = success(
        ...     "Update completed", UpdateDetails(packages_updated=45, duration_ms=1250)
        ... )
        >>> result.is_success()
        True
        >>> result.details
        UpdateDetails(packages_updated=45, duration_ms=1250)
        >>> str(result)
        '[SUCCESS] Update completed'

        >>> # Simple success without additional details
        >>> result = success("Cache cleared")
        >>> result.message
        'Cache cleared'

    See Also:
        failed: Create a failure result
        skipped: Create a skipped result
        partial: Create a partial result
    """
    return TaskResult(
        status=TaskStatus.SUCCESS,
        message=message,
        details=details,
    )


def failed[TDetails](
    message: str, error: str | None = None, details: TDetails | None = None
) -> TaskResult[TDetails]:
    """
    Create a failure result.

    A convenience factory function for creating a TaskResult with FAILURE status.
    This is the standard way to report task execution failures, optionally including
    the exception that caused the failure for debugging and error tracking.

    Args:
        message (str): Human-readable failure message describing what went wrong.
            Should be clear and specific about the nature of the failure. Examples:
            "Update check failed", "Installation failed with disk full error",
            "Network connection timeout".
        error (str | None): The error message of the exact exception
         that caused the failure.
        details (TDetails | None): A dataclass instance describing task-specific structured
            details (see core.task_details for per-task schemas), or None
            if there's nothing to report.

    Returns:
        TaskResult[TDetails]: A new TaskResult instance with:
            - status: TaskStatus.FAILURE
            - message: The provided failure message
            - error: The error message (if provided)
            - details: The provided details instance
            - timestamp: Current time (set automatically)

    Examples:
        >>> # Basic failure without exception
        >>> result = failed("System update failed")
        >>> result.is_failed()
        True
        >>> result.error is None
        True

        >>> from dataclasses import dataclass
        >>> @dataclass
        ... class ExampleTaskDetails:
        ...     retry_count: int
        >>> # Failure with exception object
        >>> def risky_operation():
        ...     raise ValueError("Raising ValueError...")
        >>> try:
        ...     risky_operation()
        ... except Exception as e:
        ...     result = failed(
        ...         "Operation failed",
        ...         error=str(e),
        ...         details=ExampleTaskDetails(retry_count=3)
        ...     )
        >>> result.is_failed()
        True
        >>> result.error is not None
        True
        >>> result.details
        ExampleTaskDetails(retry_count=3)

        >>> # Failure with detailed context
        >>> from dataclasses import dataclass
        >>> @dataclass
        ... class BackupDetails:
        ...     failed_files: int
        ...     total_files: int
        ...     backup_size_gb: float
        >>> result = failed(
        ...     "Backup failed",
        ...     error=str(IOError("Disk full")),
        ...     details=BackupDetails(
        ...         failed_files=5,
        ...         total_files=100,
        ...         backup_size_gb=50
        ...     )
        ... )
        >>> str(result)
        '[FAILURE] Backup failed Error: Disk full'

    See Also:
        success: Create a success result
        skipped: Create a skipped result
        partial: Create a partial result
    """
    return TaskResult(
        status=TaskStatus.FAILURE,
        message=message,
        error=error,
        details=details,
    )


def skipped[TDetails](
    message: str, skip_reason: SkipReason | None, details: TDetails | None = None
) -> TaskResult[TDetails]:
    """
    Create a skipped result.

    A convenience factory function for creating a TaskResult with SKIPPED status.
    This is the standard way to report tasks that were not executed, including the
    enumerated reason why they were skipped (e.g., disabled, dependency failed).

    Args:
        message (str): Human-readable message explaining why the task was skipped.
            Should provide context about the skip decision. Examples: "Task disabled
            in configuration", "Dependency task failed", "Preconditions not met",
            "Running as non-root user but root required".
        skip_reason (SkipReason | None): Enumerated reason for skipping from the
            SkipReason enum. Provides machine-readable categorization of skip reasons
            for programmatic handling. Can be None if no specific reason applies.
            Examples: DISABLED, DEPENDENCY_FAILED, NOT_DUE.
        details (TDetails | None): A dataclass instance describing task-specific structured
            details (see core.task_details for per-task schemas), or None
            if there's nothing to report.

    Returns:
        TaskResult[TDetails]: A new TaskResult instance with:
            - status: TaskStatus.SKIPPED
            - message: The provided skip message
            - skip_reason: The enumerated skip reason
            - details: The provided details instance
            - timestamp: Current time (set automatically)

    Examples:
        >>> # Skip due to disabled configuration
        >>> result = skipped(
        ...     "Task disabled in configuration",
        ...     skip_reason=SkipReason.DISABLED
        ... )
        >>> result.is_skipped()
        True
        >>> result.skip_reason == SkipReason.DISABLED
        True

        >>> # Skip due to failed dependency
        >>> result = skipped(
        ...     "Dependency task 'system-update' failed",
        ...     skip_reason=SkipReason.DEPENDENCY_FAILED,
        ... )
        >>> result.is_skipped()
        True

    See Also:
        success: Create a success result
        failed: Create a failure result
        partial: Create a partial result
        SkipReason: Enumeration of skip reason types
    """
    return TaskResult(
        status=TaskStatus.SKIPPED,
        message=message,
        skip_reason=skip_reason,
        details=details,
    )


def partial[TDetails](
    message: str, details: TDetails | None = None
) -> TaskResult[TDetails]:
    """
    Create a partial result.

    A convenience factory function for creating a TaskResult with PARTIAL status.
    Use this when a task makes progress but does not fully complete or fully succeed,
    such as when some checks pass while others fail, or when partial data is recovered
    from a failed operation.

    Args:
        message (str): Human-readable status message describing the partial completion.
            Should clearly indicate what succeeded and what didn't. Examples:
            "3 of 5 checks passed", "Found 3 failed service(s) requiring attention",
            "Health check found 2 warning(s)".
        details (TDetails | None): A dataclass instance describing task-specific structured
            details (see core.task_details for per-task schemas), or None
            if there's nothing to report.

    Returns:
        TaskResult[TDetails]: A new TaskResult instance with:
            - status: TaskStatus.PARTIAL
            - message: The provided status message
            - details: The provided details instance
            - timestamp: Current time (set automatically)

    Examples:
        >>> result = partial(message="Health check found 2 warning(s)")
        >>> result.is_partial()
        True

    See Also:
        success: Create a success result
        failed: Create a failure result
        skipped: Create a skipped result
    """
    return TaskResult(
        status=TaskStatus.PARTIAL,
        message=message,
        details=details,
    )
