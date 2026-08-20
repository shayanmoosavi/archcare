"""
Domain exceptions for the Archcare config layer.

Defines custom exceptions used for error handling and validation failures
during configuration loading, parsing, and modification. All exceptions
root back to [ArchcareError][archcare.exceptions.ArchcareError].

Certain exception classes deliberately subclass both [ArchcareConfigError][]
and `ValueError` so that they propagate correctly through Pydantic validators
(which wrap standard `ValueError` instances in `ValidationError`).

See Also:
    - [archcare.exceptions][]: Base application exception definitions
    - [archcare.config.loader][]: Config loader that handles and logs these exceptions
"""

from archcare.exceptions import ArchcareError


class ArchcareConfigError(ArchcareError):
    """
    Base class for domain exceptions raised by the config layer.

    All exceptions specific to TOML parsing, path resolution, value validation,
    and missing config items should inherit from this class to allow callers to
    catch config-related issues specifically.
    """


class UnknownTaskError(ArchcareConfigError, ValueError):
    """
    Raised when a task name doesn't exist in [TasksConfig][].

    Subclasses `ValueError` to propagate correctly through any higher-level
    validation code.

    Attributes:
        task_name (str): The name of the task that was not found.
    """

    def __init__(self, task_name: str) -> None:
        """
        Initialize the unknown task error.

        Args:
            task_name (str): Name of the non-existent task.

        Examples:
            >>> try:
            ...     raise UnknownTaskError("invalid-task")
            ... except UnknownTaskError as e:
            ...     str(e)
            'Task not found: invalid-task'

        See Also:
            [TasksConfig][]: The task configurations container
        """
        self.task_name = task_name
        super().__init__(f"Task not found: {task_name}")


class InvalidTaskTypeFilterError(ArchcareConfigError):
    """
    Raised when filtering tasks with an invalid type.

    Occurs when [TasksConfig.get_tasks_by_type][]
    is given a value other than 'automated' or 'manual'.

    Attributes:
        task_type (str): The invalid task type filter that was supplied.
    """

    def __init__(self, task_type: str) -> None:
        """
        Initialize the invalid task type filter error.

        Args:
            task_type (str): The invalid task type value.

        Examples:
            >>> try:
            ...     raise InvalidTaskTypeFilterError("on-demand")
            ... except InvalidTaskTypeFilterError as e:
            ...     str(e)
            "task_type must be 'automated' or 'manual'"

        See Also:
            - [TasksConfig.get_tasks_by_type][]: Method raising this error
            - [TaskType][]: Enumeration of valid task types
        """
        self.task_type = task_type
        super().__init__("task_type must be 'automated' or 'manual'")


class HomeDirectoryResolutionError(ArchcareConfigError, ValueError):
    """
    Raised when a user's home directory cannot be resolved.

    Must inherit from `ValueError` because it is raised within Pydantic's
    validation lifecycle (specifically during `model_validator` or property
    access), and Pydantic wraps standard value errors into `ValidationError`.

    Attributes:
        username (str): The username for whom home directory resolution failed.
    """

    def __init__(self, username: str) -> None:
        """
        Initialize the home directory resolution error.

        Args:
            username (str): Username whose home directory could not be resolved.

        Examples:
            >>> try:
            ...     raise HomeDirectoryResolutionError("ghost")
            ... except HomeDirectoryResolutionError as e:
            ...     print(str(e))
            Cannot resolve home directory for user 'ghost'. User does not exist or is not queryable.

        See Also:
            [AppSettings.home_dir][]: Uses this during home path validation
        """
        self.username = username
        super().__init__(
            f"Cannot resolve home directory for user '{username}'. "
            f"User does not exist or is not queryable."
        )


class InvalidUnitNameError(ArchcareConfigError, ValueError):
    """
    Raised when a systemd unit name is malformed.

    Must inherit from `ValueError` because it is raised from within a Pydantic
    `field_validator` in [IgnoredServicesConfig][].

    Attributes:
        invalid_names (list[str]): List of malformed systemd unit names.

    Examples:
        >>> try:
        ...     raise InvalidUnitNameError(["bad-name@", "no-extension"])
        ... except InvalidUnitNameError as e:
        ...     print(str(e))
        Invalid systemd unit name(s) in ignored-services config: ['bad-name@', 'no-extension']

    See Also:
        [IgnoredServicesConfig][]: Validates ignored service names
    """

    def __init__(self, invalid_names: list[str]) -> None:
        """
        Initialize the invalid unit name error.

        Args:
            invalid_names (list[str]): The invalid unit names encountered.
        """
        self.invalid_names = invalid_names
        super().__init__(
            f"Invalid systemd unit name(s) in ignored-services config: {invalid_names}"
        )
