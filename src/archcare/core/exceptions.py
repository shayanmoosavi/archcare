"""
Domain exceptions for the Archcare core layer.

This module defines the exception hierarchy specific to the core execution layer,
providing typed errors for task registration, execution, and scheduling failures.

Exception Hierarchy:
    ```ansi
    ArchcareError (base)
        └── ArchcareCoreError
            └── TaskNotRegisteredError
    ```

These exceptions are raised by:

- [TaskRegistry][] when looking up unregistered tasks
- [TaskExecutor][archcare.core.executor.TaskExecutor] during task instantiation

All core exceptions inherit from [ArchcareCoreError][], which extends the project's root
[ArchcareError][archcare.exceptions.ArchcareError].
This allows catching all core-layer errors with a single `except ArchcareCoreError`
block while still distinguishing specific error types.

Examples:
    >>> from archcare.core.exceptions import ArchcareCoreError, TaskNotRegisteredError
    >>> try:
    ...     raise TaskNotRegisteredError("unknown-task", ["A", "B"])
    ... except ArchcareCoreError as e:
    ...     print(type(e).__name__)
    TaskNotRegisteredError

See Also:
    - [archcare.exceptions][]: Root exception hierarchy
    - [archcare.core.task_registry][]: Task registry that raises these exceptions
    - [archcare.core.executor][]: Task executor that catches and handles these errors
"""

from archcare.exceptions import ArchcareError


class ArchcareCoreError(ArchcareError):
    """
    Base class for domain exceptions raised by the core layer.

    All core-layer exceptions inherit from this class, enabling catch-all
    error handling for the core module while preserving specific exception
    types for targeted handling.

    Examples:
        >>> from archcare.core.exceptions import ArchcareCoreError
        >>> raise ArchcareCoreError("Core layer error")
        Traceback (most recent call last):
        ...
        archcare.core.exceptions.ArchcareCoreError: Core layer error
    """


class TaskNotRegisteredError(ArchcareCoreError):
    """
    Raised when a task name has no corresponding class in the
    [TaskRegistry][].

    This occurs when:
        - CLI requests a task not in `DEFAULT_TASK_REGISTRY` (see `cli/context.py` source code)
        - [TaskExecutor][archcare.core.executor.TaskExecutor] tries to instantiate an unknown task
        - Configuration references a task that was removed from the registry

    Args:
        task_name (str): The name of the task that was not found in the registry.
        available_tasks (list[str]): The list of the available tasks in the registry.

    Examples:
        >>> from archcare.core.exceptions import TaskNotRegisteredError
        >>> raise TaskNotRegisteredError( # doctest: +NORMALIZE_WHITESPACE
        ...     "nonexistent-task",
        ...     ["A", "B"],
        ... )
        Traceback (most recent call last):
        ...
        archcare.core.exceptions.TaskNotRegisteredError: No task registered for:
            'nonexistent-task'. Available tasks: ['A', 'B']
    """

    def __init__(self, task_name: str, available_tasks: list[str]):
        super().__init__(
            f"No task registered for: '{task_name}'. Available tasks: {available_tasks}"
        )
        self.task_name = task_name
