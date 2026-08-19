"""Domain exceptions for the Archcare core layer."""

from archcare.exceptions import ArchcareError


class ArchcareCoreError(ArchcareError):
    """Base class for domain exceptions raised by the core layer."""


class TaskNotRegisteredError(ArchcareCoreError):
    """Raised when a task name has no corresponding class in the [TaskRegistry][TaskRegistry]."""
