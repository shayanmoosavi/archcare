"""Domain exceptions for the Archcare config layer."""

from archcare.exceptions import ArchcareError


class ArchcareConfigError(ArchcareError):
    """Base class for domain exceptions raised by the config layer."""


class UnknownTaskError(ArchcareConfigError, ValueError):
    """Raised when a task name doesn't exist in TasksConfig."""

    def __init__(self, task_name: str) -> None:
        self.task_name = task_name
        super().__init__(f"Task not found: {task_name}")


class InvalidTaskTypeFilterError(ArchcareConfigError):
    """
    Raised when TasksConfig.get_tasks_by_type() is given something other
    than 'automated'/'manual'.
    """

    def __init__(self, task_type: str) -> None:
        self.task_type = task_type
        super().__init__("task_type must be 'automated' or 'manual'")


class HomeDirectoryResolutionError(ArchcareConfigError, ValueError):
    """
    Raised when a user's home directory can't be resolved via pwd or the
    /home/ fallback. Must keep ValueError in its MRO - this propagates
    through home_dir -> validate_paths(), a Pydantic model_validator,
    which only wraps ValueError/TypeError/AssertionError into
    ValidationError.
    """

    def __init__(self, username: str) -> None:
        self.username = username
        super().__init__(
            f"Cannot resolve home directory for user '{username}'. "
            f"User does not exist or is not queryable."
        )


class InvalidUnitNameError(ArchcareConfigError, ValueError):
    """
    Raised when a configured ignored-service entry isn't a valid systemd
    unit name. Must keep ValueError in its MRO because it's raised from within a
    Pydantic field_validator.
    """

    def __init__(self, invalid_names: list[str]) -> None:
        self.invalid_names = invalid_names
        super().__init__(
            f"Invalid systemd unit name(s) in ignored-services config: {invalid_names}"
        )
