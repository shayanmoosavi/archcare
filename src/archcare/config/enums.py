"""
Enumeration types for the Archcare configuration layer.

This module defines the core enumeration types used across Archcare's configuration
and state management systems. These enums provide type-safe constants for:

- **LogLevel**: Logging verbosity levels (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`)
- **TaskType**: Execution modes for maintenance tasks (`AUTOMATED`, `MANUAL`)
- **TaskStatus**: Outcome states for task runs (`SUCCESS`, `FAILURE`, `SKIPPED`, `PARTIAL`)
- **SkipReason**: Enumerated reasons why a task was not executed

All enums inherit from `enum.Enum` and implement `__str__` to return their
string value, enabling direct serialization to TOML/JSON configuration files.

These enums are used by:
    - [`AppSettings`][] for logging configuration
    - [`TaskConfig`][] for task definitions
    - [`TaskState`][] for runtime state tracking
    - [`ConfigLoader`][] for validation

Examples:
    >>> from archcare.config.enums import LogLevel, TaskType, TaskStatus, SkipReason
    >>> LogLevel.INFO
    <LogLevel.INFO: 'INFO'>
    >>> TaskType.AUTOMATED
    <TaskType.AUTOMATED: 'automated'>
    >>> TaskStatus.SUCCESS
    <TaskStatus.SUCCESS: 'success'>
    >>> SkipReason.NOT_DUE
    <SkipReason.NOT_DUE: 'not_due'>

See Also:
    - [`archcare.config.models`][]: Pydantic models that use these enums
    - [`archcare.config.loader`][]: Configuration loading with enum validation
"""

from enum import Enum


class LogLevel(Enum):
    """
    Represent logging severity levels for Archcare operations.

    Controls which log messages are written to log files. Higher severity levels
    include messages from lower levels (e.g., `ERROR` includes `ERROR` and `CRITICAL`).
    This is configured globally in settings to control terminal and file output verbosity.

    Attributes:
        DEBUG (str): Detailed debugging info, variable values, and function calls.
        INFO (str): Normal operational events (e.g., "Task started", "Mirror list updated").
        WARNING (str): Non-critical issues or warnings (e.g., "Task overdue", "Old log files
            deleted").
        ERROR (str): Task failures, errors, and exceptions.
        CRITICAL (str): Severe, system-level failures that affect the operation of Archcare.

    Configuration Examples:
        ```toml title="tasks.toml"
        log_level = "INFO"  # Typical production setting
        log_level = "DEBUG" # Troubleshooting mode
        ```

    Examples:
        >>> from archcare.config.enums import LogLevel
        >>> LogLevel.INFO
        <LogLevel.INFO: 'INFO'>
        >>> str(LogLevel.INFO)
        'INFO'

    See Also:
        [`AppSettings`][archcare.config.models.AppSettings]: App-wide settings where this log level
            is applied
    """

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

    def __str__(self) -> str:
        """
        Return the string representation of the log level.

        Returns:
            str: The string value of the log level.

        Examples:
            >>> from archcare.config.enums import LogLevel
            >>> str(LogLevel.INFO)
            'INFO'
        """
        return self.value


class TaskType(Enum):
    """
    Represent task execution modes for Archcare.

    Specifies whether the task should be executed automatically or manually.
    Automated tasks are triggered via systemd timers at scheduled intervals,
    while manual tasks must be explicitly run by the user.

    Attributes:
        AUTOMATED (str): Tasks executed automatically on scheduled intervals.
        MANUAL (str): Tasks executed manually by the user.

    Configuration Examples:
        ```toml title="tasks.toml"
        [health-check]
        type = "automated"      # Runs automatically on schedule
        frequency = 7           # Every 7 days

        [mirrorlist-update]
        type = "manual"         # User must run explicitly
        frequency = 15          # User should run every 15 days
        ```

    Examples:
        >>> from archcare.config.enums import TaskType
        >>> TaskType.AUTOMATED
        <TaskType.AUTOMATED: 'automated'>
        >>> str(TaskType.AUTOMATED)
        'automated'

    See Also:
        [`TaskConfig`][archcare.config.models.TaskConfig]: Configuration where task type
        is specified
    """

    AUTOMATED = "automated"
    MANUAL = "manual"

    def __str__(self) -> str:
        """
        Return the string representation of the task type.

        Returns:
            str: The string value of the task type.

        Examples:
            >>> from archcare.config.enums import TaskType
            >>> str(TaskType.AUTOMATED)
            'automated'
        """
        return self.value


class TaskStatus(Enum):
    """
    Represent the execution outcome for a completed task run.

    Tracks whether a task was successful, failed, skipped, or had partial success. The resulting
    status is persisted in the application state to track history and make future scheduling
    decisions.

    Attributes:
        SUCCESS (str): Task completed without errors, accomplishing all work.
        FAILURE (str): Task encountered a critical error and was incomplete.
        SKIPPED (str): Task was not run; preserved for auditing and status reporting.
        PARTIAL (str): Task completed with mixed results (some parts succeeded, others had issues).

    Examples:
        >>> from archcare.config.enums import TaskStatus
        >>> TaskStatus.SUCCESS
        <TaskStatus.SUCCESS: 'success'>
        >>> str(TaskStatus.SUCCESS)
        'success'

    See Also:
        [`TaskState`][archcare.config.models.TaskState]: State model containing task
        execution status
    """

    SUCCESS = "success"
    FAILURE = "failure"
    SKIPPED = "skipped"
    PARTIAL = "partial"

    def __str__(self) -> str:
        """
        Return the string representation of the task status.

        Returns:
            str: The string value of the task status.

        Examples:
            >>> from archcare.config.enums import TaskStatus
            >>> str(TaskStatus.SUCCESS)
            'success'
        """
        return self.value


class SkipReason(Enum):
    """
    Represent the enumerated reasons why a task execution was skipped.

    Provides semantic categorization for task skips, allowing the scheduling and reporting
    components to handle different skip scenarios correctly (e.g. advancing schedules or
    raising warnings).

    Attributes:
        NO_WORK_NEEDED (str): Task ran but found no system changes or work required.
        DISABLED (str): Task is disabled in the configuration file.
        DEPENDENCY_FAILED (str): Task requires a missing system command or program.
        USER_CANCELLED (str): User explicitly declined to run the task when prompted.
        NOT_DUE (str): Task is not due for execution according to its frequency schedule.
        OTHER (str): Miscellaneous or custom skip reason specified by the task implementation.

    Examples:
        >>> from archcare.config.enums import SkipReason
        >>> SkipReason.DISABLED
        <SkipReason.DISABLED: 'disabled'>
        >>> str(SkipReason.DISABLED)
        'disabled'

    See Also:
        [`TaskExecutor`][archcare.core.executor.TaskExecutor]: Coordinates task handling
            and schedule state updates
    """

    NO_WORK_NEEDED = "no_work_needed"
    DISABLED = "disabled"
    DEPENDENCY_FAILED = "dependency_failed"
    USER_CANCELLED = "user_cancelled"
    NOT_DUE = "not_due"
    OTHER = "other"

    def __str__(self) -> str:
        """
        Return the string representation of the skip reason.

        Returns:
            str: The string value of the skip reason.

        Examples:
            >>> from archcare.config.enums import SkipReason
            >>> str(SkipReason.DISABLED)
            'disabled'
        """
        return self.value
