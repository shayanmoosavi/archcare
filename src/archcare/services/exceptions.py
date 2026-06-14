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
