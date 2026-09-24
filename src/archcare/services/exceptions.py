"""
Domain exceptions for the Archcare service layer.

This module defines the exception hierarchy for [`archcare.services`][]. All exceptions derive from
`ArchcareServiceError`, which in turn derives from the global [`ArchcareError`][] root. This lets
the CLI catch all service-layer failures with a single `except ArchcareError` clause while still
allowing precise per-exception handling where needed.

Exception map:

|            Exception                |                     Raised when                      |
| ----------------------------------- | ---------------------------------------------------- |
| [`TaskNotFoundError`][]             | A task name isn't present in tasks.toml              |
| [`InvalidTasksFileError`][]         | The tasks file is empty                              |
| [`InvalidTaskTypeError`][]          | A `--type` filter isn't 'automated' or 'manual'      |
| [`NotRootError`][]                  | A sudo-required command runs without root            |
| [`UserDetectionError`][]            | Target user can't be resolved during systemd setup   |
| [`SystemdReloadError`][]            | `systemctl daemon-reload` fails                      |
| [`ConfigNotInitializedError`][]     | Configuration doesn't exist yet (no tasks.toml)      |
| [`InvalidSeverityError`][]          | A severity argument isn't critical/warning/info      |
| [`NotificationUnavailableError`][]  | `notify-send`/libnotify is missing                   |
| [`NotificationSendError`][]         | A test notification fails to send                    |

Exceptions carrying contextual data (e.g., the offending task name or severity) expose it as public
attributes so callers can build richer messages.

Exception Hierarchy:
    ```mermaid
    flowchart LR
    BASE["ArchcareError (base)"]
    SVC[ArchcareServiceError]

    BASE --> SVC --> A[Errors in this module]
    ```

See Also:
    - [`ArchcareError`][]: Root exception for all Archcare exceptions
    - [`TaskService`][archcare.services.task_service.TaskService]: Primary raiser of
        task-related errors
    - [`archcare.services.setup_service`][]: Raises setup/systemd-related errors
    - [`archcare.services.debug_service`][]: Raises notification-related errors
"""

from archcare.exceptions import ArchcareError


class ArchcareServiceError(ArchcareError):
    """
    Base class for all service-layer errors.

    Subclasses of this exception represent recoverable, user-facing failures in the services layer.
    Deriving from [`ArchcareError`][] means the CLI can catch the entire application error domain
    uniformly.
    """


class TaskNotFoundError(ArchcareServiceError):
    """
    Raised when a referenced task name does not exist in configuration.

    Attributes:
        task_name (str): The unknown task name that was requested.
    """

    def __init__(self, task_name: str) -> None:
        """
        Create the error for an unknown task.

        Args:
            task_name (str): The task name that could not be found.
        """
        self.task_name = task_name
        super().__init__(f"Task not found: {task_name}")


class InvalidTasksFileError(ArchcareServiceError):
    """
    Raised when the tasks file is empty.

    An empty `tasks.toml` means no task can be resolved, so dependent operations (listing, running,
    scheduling) cannot proceed.
    """

    def __init__(self):
        super().__init__("Tasks file is empty!")


class InvalidTaskTypeError(ArchcareServiceError):
    """
    Raised when a task type filter is neither 'automated' nor 'manual'.

    Attributes:
        task_type (str): The invalid filter value that was supplied.
    """

    def __init__(self, task_type: str) -> None:
        """
        Create the error for an unrecognized task type filter.

        Args:
            task_type (str): The invalid filter value supplied by the caller.
        """
        self.task_type = task_type
        super().__init__(f"Invalid task type: {task_type!r} (expected 'automated' or 'manual')")


class NotRootError(ArchcareServiceError):
    """
    Raised when a command requiring root privileges is run without it.

    Typically triggered by `archcare setup timers`, which must install system-level systemd units.
    """

    def __init__(self) -> None:
        super().__init__("This command needs root privilege and should be run with sudo.")


class UserDetectionError(ArchcareServiceError):
    """
    Raised when the target (non-root) user for systemd setup can't be determined.

    Occurs during `archcare setup timers` when running as root but neither `ARCHCARE_USER` nor
    `SUDO_USER` is set (or `SUDO_USER` refers to a nonexistent user), so the installer can't decide
    which user's systemd units to manage.

    See Also:
        - [`UserContext`][archcare.config.user.UserContext]: Resolves the target user
    """


class SystemdReloadError(ArchcareServiceError):
    """
    Raised when `systemctl daemon-reload` fails.

    After installing or removing systemd timer units, a reload is required for changes to take
    effect; a failure here leaves the system in an inconsistent unit state.
    """

    def __init__(self) -> None:
        super().__init__("Failed to reload systemd")


class ConfigNotInitializedError(ArchcareServiceError):
    """
    Raised when a command requiring configuration is run before `archcare setup config` has been
    executed.

    Detected by the absence of `tasks.toml` in the config directory. Caught centrally in `main()` so
    every command gets the same clear message without per-command handling.
    """

    def __init__(self) -> None:
        super().__init__("Archcare is not initialized.")


class InvalidSeverityError(ArchcareServiceError):
    """
    Raised when a notification severity isn't critical/warning/info.

    Attributes:
        severity (str): The invalid severity value that was supplied.
        valid (list[str]): The accepted severity values.
    """

    def __init__(self, severity: str, valid: list[str]) -> None:
        """
        Create the error for an unrecognized notification severity.

        Args:
            severity (str): The invalid severity value supplied by the caller.
            valid (list[str]): List of accepted severity values, included in the error message.
        """
        self.severity = severity
        self.valid = valid
        super().__init__(f"Invalid severity: {severity!r} (expected one of {valid})")


class NotificationUnavailableError(ArchcareServiceError):
    """
    Raised when notify-send/libnotify isn't available on this system.

    Detected by the lazy availability check in
    [`NotificationManager`][archcare.core.notifications.NotificationManager];
    prevents attempting to send notifications on headless or minimal systems.
    """


class NotificationSendError(ArchcareServiceError):
    """
    Raised when send_notification() reports failure.

    Indicates libnotify is available but the notification command itself
    failed (e.g., no notification daemon running in the session).

    Attributes:
        severity (str): The severity of the notification that failed to send.
    """

    def __init__(self, severity: str) -> None:
        """
        Create the error for a failed notification send.

        Args:
            severity (str): Severity label of the failed notification
                (e.g., `"critical"`).
        """
        self.severity = severity
        super().__init__(f"Failed to send {severity} test notification")
