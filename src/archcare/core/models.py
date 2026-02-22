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
    - MaintenanceCheckResult: Comprehensive result from maintenance checks
    - Helper functions: Factory functions for creating TaskResult instances

Key Features:
    - Status tracking with multiple states (SUCCESS, FAILURE, SKIPPED, PARTIAL)
    - Detailed error tracking and exception handling
    - Real-time progress reporting through TaskStep objects
    - Maintenance issue classification by severity
    - Conversion utilities between different result formats

All classes use Pydantic BaseModel or dataclasses for validation and
serialization support, enabling integration with APIs and logging systems.

See Also:
    archcare.config.models: Task status enums and configuration data models
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
        details (dict[str, Any]): Optional structured data providing additional
            context about the execution. Keys are context-specific and may
            include counts, resource names, file paths, etc. Defaults to empty.
        error (Exception | None): The exception object that caused the failure,
            if applicable. Preserved for debugging and log analysis. Defaults
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
        skip_message (str | None): Human-readable explanation of why the task
            was skipped. May provide additional context beyond skip_reason.
            Defaults to None.
        error_message (str | None): String representation of the error for
            cases where the exception object is not available or serializable.
            Useful for logging and API responses. Defaults to None.

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
        ...     details={"packages_updated": 45},
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
        ...         error=e,
        ...         error_message=str(e)
        ...     )

    See Also:
        TaskStatus: Enumeration of possible task statuses
        SkipReason: Enumeration of reasons why a task might be skipped
        TaskStep: For reporting granular progress during execution
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
            ...     details={"passed": 3, "failed": 2}
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
            ...     error=exc,
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
            functionality. Example: Severly overdue maintenance tasks or broken
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


class MaintenanceIssue(BaseModel):
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

    Methods:
        is_overdue() -> bool: Property that returns True if days_overdue is
            positive (task overdue), False otherwise.

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


class MaintenanceCheckResult(BaseModel):
    """
    Comprehensive result of a maintenance check task execution.

    MaintenanceCheckResult aggregates all maintenance issues discovered during
    the maintenance-check task, organizing them by severity level and providing
    summary statistics and helper methods for analysis.

    This model is designed to be returned by maintenance-check task and provides
    a complete picture of the system's maintenance status, including critical
    issues requiring immediate attention, warnings that should be addressed soon,
    and informational updates.

    Attributes:
        task_name (str): Identifier for this maintenance check task. Defaults
            to "maintenance-check". Used to track which task produced this result.
        status (TaskStatus): Overall status of the maintenance check execution.
            Can be SUCCESS (check completed), FAILURE (check failed to run),
            SKIPPED (check was skipped), or PARTIAL (check ran but found issues).
        timestamp (datetime): When the maintenance check was performed. Automatically
            set to the current time. Useful for tracking when checks occurred and
            aging the results.
        critical_issues (list[MaintenanceIssue]): List of critical issues requiring
            immediate attention (see MaintenanceIssue for more details). Defaults to
            empty.
        warning_issues (list[MaintenanceIssue]): List of warning-level issues that
            should be addressed soon but are not critical (see MaintenanceIssue for
            more details). Defaults to empty.
        info_issues (list[MaintenanceIssue]): List of informational issues providing
            status updates or reminders. No immediate action needed. Defaults to empty.
        total_tasks_monitored (int): Total count of tasks that were checked. Provides
            context for the completeness of the maintenance check. Defaults to 0.
        error_message (str | None): Error message if the maintenance check itself
            failed to execute properly. Defaults to None for successful checks.

    Properties:
        all_issues (list[MaintenanceIssue]): Get all issues combined and sorted by
            severity (critical, then warning, then info).
        tasks_needing_attention (list[MaintenanceIssue]): Get only important issues
            (critical and warning), excluding informational ones.
        has_issues (bool): Quick check to determine if any issues were found.
        summary_message (str): Generate a human-readable summary message describing
            the overall maintenance status.

    Methods:
        get_issues_by_severity(severity: IssueSeverity) -> list[MaintenanceIssue]:
            Filter and retrieve issues by a specific severity level.
        to_task_result() -> TaskResult: Convert this comprehensive result to a
            standard TaskResult format for integration with other components.

    Examples:
        >>> # Create a maintenance check with some issues
        >>> check = MaintenanceCheckResult(
        ...     status=TaskStatus.PARTIAL,
        ...     total_tasks_monitored=5,
        ...     critical_issues=[
        ...         MaintenanceIssue(
        ...             task_name="system-update",
        ...             severity=IssueSeverity.CRITICAL,
        ...             description="System updates are 20 days overdue",
        ...             days_overdue=20,
        ...             recommendation="Run system update immediately"
        ...         )
        ...     ],
        ...     warning_issues=[
        ...         MaintenanceIssue(
        ...             task_name="cache-cleanup",
        ...             severity=IssueSeverity.WARNING,
        ...             description="Cache hasn't been cleaned in 30 days",
        ...             days_overdue=5,
        ...             recommendation="Run cache cleanup task"
        ...         )
        ...     ]
        ... )
        >>> check.has_issues
        True
        >>> print(check.summary_message)
        Found 1 critical, 1 warning issue(s) requiring attention
        >>> critical = check.get_issues_by_severity(IssueSeverity.CRITICAL)
        >>> len(critical)
        1

        >>> # Convert to TaskResult for compatibility
        >>> task_result = check.to_task_result()
        >>> task_result.is_partial()
        True

    See Also:
        MaintenanceIssue: Individual maintenance issues
        IssueSeverity: Severity classification
        TaskStatus: Execution status enumeration
    """

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
        """
        Get all issues sorted by severity.

        Returns all issues (critical, warning, and informational) combined into
        a single list, ordered by severity level with critical issues first.

        Returns:
            list[MaintenanceIssue]: All issues from the check, ordered by severity.

        Examples:
            >>> check = MaintenanceCheckResult(
            ...     status=TaskStatus.PARTIAL,
            ...     critical_issues=[issue1],
            ...     warning_issues=[issue2, issue3],
            ...     info_issues=[issue4]
            ... )
            >>> len(check.all_issues)
            4
            >>> check.all_issues[0].severity == IssueSeverity.CRITICAL
            True
        """
        return self.critical_issues + self.warning_issues + self.info_issues

    @property
    def tasks_needing_attention(self) -> list[MaintenanceIssue]:
        """
        Get all important issues sorted by severity.

        Returns critical and warning issues, excluding informational ones. This is
        useful when you need to focus on actionable problems that require attention.

        Returns:
            list[MaintenanceIssue]: Critical and warning issues combined, in that
                order. Informational issues are excluded.

        Examples:
            >>> check = MaintenanceCheckResult(
            ...     status=TaskStatus.PARTIAL,
            ...     critical_issues=[issue1],
            ...     warning_issues=[issue2],
            ...     info_issues=[issue3]
            ... )
            >>> len(check.tasks_needing_attention)
            2
            >>> issue3 in check.tasks_needing_attention
            False
        """
        return self.critical_issues + self.warning_issues

    @property
    def has_issues(self) -> bool:
        """
        Check if there are any issues at all.

        Returns True if any issues (critical, warning, or informational) were found
        during the maintenance check.

        Returns:
            bool: True if the check found any issues, False if all systems are healthy.

        Examples:
            >>> # Check with issues
            >>> check = MaintenanceCheckResult(
            ...     status=TaskStatus.PARTIAL,
            ...     critical_issues=[issue1]
            ... )
            >>> check.has_issues
            True

            >>> # Check with no issues
            >>> check = MaintenanceCheckResult(
            ...     status=TaskStatus.SUCCESS,
            ...     critical_issues=[],
            ...     warning_issues=[],
            ...     info_issues=[]
            ... )
            >>> check.has_issues
            False
        """
        return len(self.all_issues) > 0

    @property
    def summary_message(self) -> str:
        """
        Generate a human-readable summary message.

        Returns a concise, one-line summary of the maintenance check results. For
        checks with no issues, returns an "all clear" message. For checks with issues,
        returns a count breakdown by severity level.

        Returns:
            str: A human-readable summary message suitable for logging or display.

        Examples:
            >>> # Check with all systems healthy
            >>> check = MaintenanceCheckResult(
            ...     status=TaskStatus.SUCCESS,
            ...     critical_issues=[],
            ...     warning_issues=[],
            ...     info_issues=[]
            ... )
            >>> print(check.summary_message)
            All maintenance tasks are up to date!

            >>> # Check with multiple issue types
            >>> check = MaintenanceCheckResult(
            ...     status=TaskStatus.PARTIAL,
            ...     critical_issues=[issue1, issue2],
            ...     warning_issues=[issue3],
            ...     info_issues=[]
            ... )
            >>> print(check.summary_message)
            Found 2 critical, 1 warning issue(s) requiring attention

            >>> # Check with only informational issues
            >>> check = MaintenanceCheckResult(
            ...     status=TaskStatus.PARTIAL,
            ...     critical_issues=[],
            ...     warning_issues=[],
            ...     info_issues=[issue1, issue2, issue3]
            ... )
            >>> print(check.summary_message)
            Found 3 info issue(s) requiring attention
        """
        if not self.has_issues:
            return "All maintenance tasks are up to date!"

        parts = []
        if self.critical_issues:
            parts.append(f"{len(self.critical_issues)} critical")
        if self.warning_issues:
            parts.append(f"{len(self.warning_issues)} warning")
        if self.info_issues:
            parts.append(f"{len(self.info_issues)} info")

        return f"Found {', '.join(parts)} issue(s) requiring attention"

    def get_issues_by_severity(self, severity: IssueSeverity) -> list[MaintenanceIssue]:
        """
        Get issues filtered by a specific severity level.

        Returns all issues that match the specified severity classification, enabling
        filtering of the issue list to focus on particular priority levels.

        Args:
            severity (IssueSeverity): The severity level to filter by. Can be
                CRITICAL, WARNING, or INFO.

        Returns:
            list[MaintenanceIssue]: All issues matching the specified severity,
                in the order they were added to the result.

        Examples:
            >>> check = MaintenanceCheckResult(
            ...     status=TaskStatus.PARTIAL,
            ...     critical_issues=[issue1, issue2],
            ...     warning_issues=[issue3],
            ...     info_issues=[issue4]
            ... )
            >>> critical = check.get_issues_by_severity(IssueSeverity.CRITICAL)
            >>> len(critical)
            2
            >>> critical[0].task_name
            'system-update'

            >>> warning = check.get_issues_by_severity(IssueSeverity.WARNING)
            >>> len(warning)
            1

            >>> info = check.get_issues_by_severity(IssueSeverity.INFO)
            >>> len(info)
            1
        """
        severity_map = {
            IssueSeverity.CRITICAL: self.critical_issues,
            IssueSeverity.WARNING: self.warning_issues,
            IssueSeverity.INFO: self.info_issues,
        }
        return severity_map[severity]

    def to_task_result(self) -> TaskResult:
        """
        Convert this comprehensive result to a standard TaskResult format.

        Creates a TaskResult instance from the MaintenanceCheckResult, enabling
        integration with other archcare components that work with TaskResult objects.
        The conversion includes the summary message as the TaskResult message, and
        all issue statistics are included in the details dictionary.

        Returns:
            TaskResult: A TaskResult with:
                - status: The overall check status
                - message: The summary_message property
                - details: Dictionary containing:
                    - total_tasks_monitored: Count of tasks checked
                    - tasks_needing_attention: List of critical and warning issues
                    - critical_count: Number of critical issues
                    - warning_count: Number of warning issues
                    - info_count: Number of info issues
                - error_message: Error message if check failed (None if successful)

        Examples:
            >>> check = MaintenanceCheckResult(
            ...     status=TaskStatus.PARTIAL,
            ...     total_tasks_monitored=15,
            ...     critical_issues=[issue1, issue2],
            ...     warning_issues=[issue3]
            ... )
            >>> result = check.to_task_result()
            >>> result.is_partial()
            True
            >>> result.details['critical_count']
            2
            >>> result.details['warning_count']
            1
            >>> result.details['total_tasks_monitored']
            15

        See Also:
            TaskResult: The target format for integration with archcare components
        """
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

    A convenience factory function for creating a TaskResult with SUCCESS status.
    This is the standard way to report successful task completion.

    Args:
        message (str): Human-readable success message describing what was accomplished.
            Examples: "System updated successfully", "Cleanup completed", "All checks passed".
        **details: Additional context-specific details as keyword arguments. These are
            collected into the `details` dictionary. Common keys might include counts of
            items processed, resources updated, etc.

    Returns:
        TaskResult: A new TaskResult instance with:
            - status: TaskStatus.SUCCESS
            - message: The provided message
            - details: Dictionary created from **details keyword arguments
            - timestamp: Current time (set automatically)

    Examples:
        >>> result = success("Update completed", packages_updated=45, duration_ms=1250)
        >>> result.is_success()
        True
        >>> result.details
        {'packages_updated': 45, 'duration_ms': 1250}
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
    return TaskResult(status=TaskStatus.SUCCESS, message=message, details=details)


def failed(message: str, error: Exception | None = None, **details) -> TaskResult:
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
        error (Exception | None): The exception object that caused the failure.
            Preserved for debugging, log analysis, and exception chain tracking.
            Can be None if the failure doesn't have an associated exception or if
            the exception is not available. Defaults to None.
        **details: Additional context-specific details as keyword arguments. These are
            collected into the `details` dictionary and may include error codes,
            affected resources, partial results, retry information, etc.

    Returns:
        TaskResult: A new TaskResult instance with:
            - status: TaskStatus.FAILURE
            - message: The provided failure message
            - error: The exception object (if provided)
            - details: Dictionary created from **details keyword arguments
            - timestamp: Current time (set automatically)

    Examples:
        >>> # Basic failure without exception
        >>> result = failed("System update failed")
        >>> result.is_failed()
        True
        >>> result.error is None
        True

        >>> # Failure with exception object
        >>> def risky_operation():
        ...     raise ValueError("Raising ValueError...")
        >>> try:
        ...     risky_operation()
        ... except Exception as e:
        ...     result = failed("Operation failed", error=e, retry_count=3)
        >>> result.is_failed()
        True
        >>> result.error is not None
        True
        >>> result.details
        {'retry_count': 3}

        >>> # Failure with detailed context
        >>> result = failed(
        ...     "Backup failed",
        ...     error=IOError("Disk full"),
        ...     failed_files=5,
        ...     total_files=100,
        ...     backup_size_gb=50
        ... )
        >>> str(result)
        '[FAILURE] Backup failed Error: Disk full'

    See Also:
        success: Create a success result
        skipped: Create a skipped result
        partial: Create a partial result
    """
    return TaskResult(
        status=TaskStatus.FAILURE, message=message, error=error, details=details
    )


def skipped(message: str, skip_reason: SkipReason | None, **details) -> TaskResult:
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
        **details: Additional context-specific details as keyword arguments. These are
            collected into the `details` dictionary and may include reason codes,
            dependent task names, failed preconditions, etc.

    Returns:
        TaskResult: A new TaskResult instance with:
            - status: TaskStatus.SKIPPED
            - message: The provided skip message
            - skip_reason: The enumerated skip reason
            - skip_message: Same as message (for consistency)
            - details: Dictionary created from **details keyword arguments
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
        ...     dependent_task="system-update"
        ... )
        >>> result.is_skipped()
        True
        >>> result.details['dependent_task']
        'system-update'

        >>> # Skip with detailed context
        >>> result = skipped(
        ...     "Task is not due yet, skipping execution",
        ...     skip_reason=SkipReason.NOT_DUE,
        ...     next_due_in_days=3
        ... )
        >>> result.is_skipped()
        True
        >>> result.details['next_due_in_days']
        3

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
        skip_message=message,
        details=details,
    )


def partial(message: str, **details) -> TaskResult:
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
        **details: Additional context-specific details as keyword arguments. These are
            collected into the `details` dictionary and typically include success/failure
            counts, percentages, partially processed items, error summaries, etc.

    Returns:
        TaskResult: A new TaskResult instance with:
            - status: TaskStatus.PARTIAL
            - message: The provided status message
            - details: Dictionary created from **details keyword arguments
            - timestamp: Current time (set automatically)

    Examples:
        >>> # Health check with some issues found
        >>> result = partial(
        ...     message="Health check found 2 warning(s)",
        ...     warnings=["High CPU usage at 92%", "Disk usage at 85%"],
        ...     checks={"cpu": {...}, "disk": {...}},
        ...     total_checks=7
        ... )
        >>> result.is_partial()
        True
        >>> result.details['total_checks']
        7

        >>> # Failed services task with some services failing
        >>> result = partial(
        ...     message="Found 3 failed service(s) requiring attention",
        ...     failed_services=[
        ...         {"service": "nginx", "active": "failed", "logs": [...]},
        ...         {"service": "postgres", "active": "failed", "logs": [...]}
        ...     ],
        ...     total_failed=5,
        ...     actual_failures=3,
        ...     ignored=2,
        ...     ignored_services=["service1", "service2"]
        ... )
        >>> result.is_partial()
        True
        >>> result.details['ignored']
        2

        >>> # System check where multiple checks ran but some found issues
        >>> result = partial(
        ...     message="3 of 7 health checks passed",
        ...     passed_checks=["memory", "uptime", "filesystem"],
        ...     failed_checks=["disk_usage", "cpu_load"],
        ...     total_checks=7
        ... )
        >>> result.is_partial()
        True

    See Also:
        success: Create a success result
        failed: Create a failure result
        skipped: Create a skipped result
        MaintenanceCheckResult: For comprehensive maintenance check results
    """
    return TaskResult(status=TaskStatus.PARTIAL, message=message, details=details)
