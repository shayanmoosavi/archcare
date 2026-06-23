"""Domain exceptions for the Archcare service layer."""


class ArchcareError(Exception):
    """Base class for all service-layer errors."""


class TaskNotFoundError(ArchcareError):
    """Raised when a referenced task name does not exist in configuration."""

    def __init__(self, task_name: str) -> None:
        self.task_name = task_name
        super().__init__(f"Task not found: {task_name}")


class InvalidTaskTypeError(ArchcareError):
    """Raised when a task type filter is neither 'automated' nor 'manual'."""

    def __init__(self, task_type: str) -> None:
        self.task_type = task_type
        super().__init__(
            f"Invalid task type: {repr(task_type)} (expected 'automated' or 'manual')"
        )


class NotRootError(ArchcareError):
    """Raised when a command requiring root privileges is run without it."""

    def __init__(self) -> None:
        super().__init__(
            "This command needs root privilege and should be run with sudo."
        )


class UserDetectionError(ArchcareError):
    """
    Raised when the target (non-root) user for systemd setup can't be
    determined - either SUDO_USER isn't set, or it refers to a user that
    doesn't exist.
    """


class SystemdReloadError(ArchcareError):
    """Raised when `systemctl daemon-reload` fails."""

    def __init__(self) -> None:
        super().__init__("Failed to reload systemd")


class ConfigNotInitializedError(ArchcareError):
    """
    Raised when a command requiring configuration is run before
    `archcare setup config` has been executed.

    Detected by the absence of settings.toml in the config directory.
    Caught centrally in main() so every command gets the same clear
    message without per-command handling.
    """

    def __init__(self) -> None:
        super().__init__(
            "Archcare is not initialized. Run 'archcare setup config' to get started."
        )


class InvalidSeverityError(ArchcareError):
    """Raised when a notification severity isn't critical/warning/info."""

    def __init__(self, severity: str, valid: list[str]) -> None:
        self.severity = severity
        self.valid = valid
        super().__init__(f"Invalid severity: {severity!r} (expected one of {valid})")


class NotificationUnavailableError(ArchcareError):
    """Raised when notify-send/libnotify isn't available on this system."""

    def __init__(self) -> None:
        super().__init__("Desktop notifications are not available on this system")


class NotificationSendError(ArchcareError):
    """Raised when send_notification() reports failure."""

    def __init__(self, severity: str) -> None:
        self.severity = severity
        super().__init__(f"Failed to send {severity} test notification")
