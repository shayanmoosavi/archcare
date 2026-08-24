"""Domain exceptions for the Archcare core layer."""

from archcare.exceptions import ArchcareError


class ArchcareCoreError(ArchcareError):
    """Base class for domain exceptions raised by the core layer."""


class TaskNotRegisteredError(ArchcareCoreError):
    """Raised when a task name has no corresponding class in the [TaskRegistry][TaskRegistry]."""
    def __init__(self, task_name: str, available_tasks: list[str]):
        super().__init__(
            f"No task registered for: '{task_name}'. Available tasks: {available_tasks}"
        )
        self.task_name = task_name
