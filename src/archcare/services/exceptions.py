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
