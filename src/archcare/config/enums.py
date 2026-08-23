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
    - [AppSettings][] for logging configuration
    - [TaskConfig][] for task definitions
    - [TaskState][] for runtime state tracking
    - [ConfigLoader][] for validation

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
    - [archcare.config.models][]: Pydantic models that use these enums
    - [archcare.config.loader][]: Configuration loading with enum validation
"""

from enum import Enum


class LogLevel(Enum):
    """
    Logging severity levels for Archcare operations

    Controls which log messages are written to log files. Higher severity levels
    include messages from lower levels (e.g., `ERROR` includes `ERROR` and `CRITICAL`).

    Configuration Examples:
        ```toml title="tasks.toml"
        log_level = "INFO"  # settings.toml: typical production setting
        log_level = "DEBUG" # settings.toml: troubleshooting mode
        ```
    """

    DEBUG = "DEBUG"
    """Detailed debugging info, variable values, function calls"""

    INFO = "INFO"
    """Normal operations ("Task started", "Mirror list updated")"""

    WARNING = "WARNING"
    """Non-critical issues ("Task overdue", "Old log files deleted")"""

    ERROR = "ERROR"
    """Task failures and exceptions"""

    CRITICAL = "CRITICAL"
    """System-level failures that affect Archcare operation"""

    def __str__(self) -> str:
        """
        Return the string representation of the log level.

        Returns:
            str: The string value of the log level.

        Examples:
            >>> from archcare.config.models import LogLevel
            >>> str(LogLevel.INFO)
            'INFO'
        """
        return self.value


class TaskType(Enum):
    """
    Task execution modes for Archcare

    Examples:
        ```toml title="tasks.toml"
        [health-check]
        type = "automated"      # Runs on schedule automatically
        frequency = 7           # Every 7 days

        [mirrorlist-update]
        type = "manual"         # User must run explicitly
        frequency = 15          # User should run every 15 days
        ```
    """

    AUTOMATED = "automated"
    """
        - Executed automatically at scheduled intervals if no manual run is in progress
        - Example: health-check runs weekly without user intervention
        - Respects frequency setting; next_due is calculated from last_run + frequency days
    """

    MANUAL = "manual"
    """
        - Only executed when explicitly requested by the user (via CLI command)
        - Useful for potentially disruptive operations (mirror list updates, system upgrades)
        - frequency setting still defines how often it SHOULD run; skipped with `NOT_DUE` reason
        - User receives notifications when manual tasks are overdue
    """

    def __str__(self) -> str:
        """
        Return the string representation of the task type.

        Returns:
            str: The string value of the task type.

        Examples:
            >>> from archcare.config.models import TaskType
            >>> str(TaskType.AUTOMATED)
            'automated'
        """
        return self.value


class TaskStatus(Enum):
    """
    Execution outcome for a completed task run

    State Persistence:
        `last_status` persists in `state.json` for reporting and scheduling decisions.
    """

    SUCCESS = "success"
    """
        - Task completed without errors; all work accomplished
        - Example: `health-check` found no issues, or `mirrorlist-update` succeeded
        - `next_due` is set for the next scheduled run
    """

    FAILURE = "failure"
    """
        - Task encountered a critical error; work incomplete
        - Example: no network connection, permission denied, or task raised exception
        - Error message stored in `last_error`; user should review logs
        - `next_due` is untouched; automated task will be retried on next
            scheduled run (systemd timer)
    """

    SKIPPED = "skipped"
    """
        - Task did not run; preserved for auditing (not counted in success/failure metrics)
        - Example: task is disabled, not due yet, or missing dependency
        - `skip_reason` explains why (`NO_WORK_NEEDED`, `DISABLED`, `NOT_DUE`, etc.)
        - Does not update `next_due`; scheduling unaffected
    """

    PARTIAL = "partial"
    """
        - Task ran with mixed results; some work completed, some failed
        - Example: `health-check` found warnings (e.g., low disk space) but no
            critical failures (e.g., package file integrity check failed)
        - Less critical than `FAILURE`; usually safe to retry
        - Details in `last_error`; `next_due` updated based on partial results
    """

    def __str__(self) -> str:
        """
        Return the string representation of the task status.

        Returns:
            str: The string value of the task status.

        Examples:
            >>> from archcare.config.models import TaskStatus
            >>> str(TaskStatus.SUCCESS)
            'success'
        """
        return self.value


class SkipReason(Enum):
    """
    Enumerated reasons of why a task execution was skipped

    See also:
        [TaskExecutor][archcare.core.executor.TaskExecutor]: Uses it for task schedule handling
    """

    NO_WORK_NEEDED = "no_work_needed"
    """
        - Task ran but found nothing to do
        - Example: `failed-services` found no failed services
        - Treated as a successful run; next_due still advances
        - Important for auditing: confirms task ran, not just disabled
    """

    DISABLED = "disabled"
    """
        - Task is disabled in configuration (enabled: false)
        - Example: user temporarily disabled `mirrorlist-update` in `tasks.toml`
        - Does not affect scheduling; when re-enabled, next_due continues from where
            it left off
    """

    DEPENDENCY_FAILED = "dependency_failed"
    """
        - Required system component or dependency not available
        - Example: reflector package is not installed for mirrorlist update
        - The missing dependency is reported to the user and logged; task cannot run
            until resolved
    """

    USER_CANCELLED = "user_cancelled"
    """
        - User chose not to run task when prompted
        - Example: user said "no" when asked whether to run an already executed task
        - Task treated as explicitly declined; next_due not advanced (task still "due")
        - Useful for manual tasks where user may need to run it later
    """

    NOT_DUE = "not_due"
    """
        - Task execution window hasn't elapsed yet
        - Example: `health-check` runs monthly; next execution in 3 days
        - Applies to both automated and manual tasks; prevents unnecessary runs
    """

    OTHER = "other"
    """
        - Miscellaneous reason; check `last_error` for custom message
        - Example: resource exhaustion, unexpected executor state, or custom task logic
        - Reserved for edge cases and future extensibility
    """

    def __str__(self) -> str:
        """
        Return the string representation of the skip reason.

        Returns:
            str: The string value of the skip reason.

        Examples:
            >>> from archcare.config.models import SkipReason
            >>> str(SkipReason.DISABLED)
            'disabled'
        """
        return self.value
