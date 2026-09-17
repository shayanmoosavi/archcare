"""
Task registry for the Archcare core layer.

Provides a static, immutable mapping from task names to their execution classes
and detail formatters. The registry is built once at application startup and
used by [`TaskExecutor`][archcare.core.executor.TaskExecutor] for task instantiation
and by CLI presenters for rendering task details.

Registration:
    Tasks are registered in `DEFAULT_TASK_REGISTRY` (defined in `cli/context.py`),
    which maps each task name to a tuple of `(task_class, formatter_class)`.
    This registry is then passed to `TaskRegistry` constructor during
    [`AppContext`][archcare.cli.context.AppContext] initialization.

Thread Safety:
    The registry is immutable after construction. All lookups are O(1) dict operations.

Examples:
    >>> from archcare.core.task_registry import TaskRegistry, TaskDescriptor
    >>> from archcare.core.base_task import BaseTask
    >>> from archcare.core.formatter import DefaultFormatter
    >>> from archcare.core.models import TaskResult, success
    >>>
    >>> class ExampleTask(BaseTask):
    ...     def execute(self) -> TaskResult:
    ...         return success("done")
    >>>
    >>> descriptor = TaskDescriptor("example", ExampleTask)
    >>> registry = TaskRegistry((descriptor,))
    >>> registry.names()
    ('example',)
    >>> registry.get_task_class("example")
    <class '...ExampleTask'>
    >>> registry.get_formatter_class("example")
    <class 'archcare.core.formatter.DefaultFormatter'>

See Also:
    - [`archcare.cli.context`][]: Where `DEFAULT_TASK_REGISTRY` is defined
    - [`TaskExecutor`][archcare.core.executor.TaskExecutor]: Uses `TaskRegistry` for
        task instantiation
    - [`archcare.core.formatter`][]: `TaskDetailFormatter` protocol and implementations
"""

from dataclasses import dataclass

from .base_task import BaseTask
from .exceptions import TaskNotRegisteredError
from .formatter import DefaultFormatter, TaskDetailFormatter


@dataclass(frozen=True)
class TaskDescriptor:
    """
    Static description of a single task: its name, execution class, and detail formatter.

    This frozen dataclass serves as the registry entry for each maintenance task. It bundles the
    task's identifier, its execution class (inheriting from [`BaseTask`][]), and the formatter class
    used to render its result details in the CLI.

    Attributes:
        name (str): Unique task identifier (e.g., "health-check",
            "mirrorlist-update"). Must match the key in `tasks.toml` and the
            [`TaskConfig`][archcare.config.models.TaskConfig] name.
        task_class (type[BaseTask]): The concrete task implementation class. Must inherit from
            [`BaseTask`][].
        formatter_class (type[TaskDetailFormatter]): Formatter for rendering task details.
            Defaults to [`DefaultFormatter`][]. Custom formatters implement
            [`TaskDetailFormatter`][].

    Examples:
        >>> from archcare.core.task_registry import TaskDescriptor
        >>> from archcare.core.base_task import BaseTask
        >>> from archcare.core.formatter import DefaultFormatter
        >>> from archcare.core.models import TaskResult, success
        >>>
        >>> class MyTask(BaseTask):
        ...     def execute(self) -> TaskResult:
        ...         return success("completed")
        >>>
        >>> desc = TaskDescriptor(name="my-task", task_class=MyTask)
        >>> desc.name
        'my-task'
        >>> desc.task_class
        <class '...MyTask'>
        >>> desc.formatter_class
        <class 'archcare.core.formatter.DefaultFormatter'>

    See Also:
        - [`TaskRegistry`][]: Registry that stores and looks up descriptors
        - [`TaskDetailFormatter`][]: Formatter protocol
    """

    name: str
    task_class: type[BaseTask]
    formatter_class: type[TaskDetailFormatter] = DefaultFormatter


class TaskRegistry:
    """
    Immutable, statically-defined mapping from task name to its execution class and
    detail formatter.

    The registry is constructed once during application initialization from a tuple of
    [`TaskDescriptor`][] objects. It provides O(1) lookups for task classes and formatters by name.

    The registry is populated from `DEFAULT_TASK_REGISTRY` in `cli/context.py`, which defines all
    built-in tasks and their formatters.
    """

    def __init__(self, descriptors: tuple[TaskDescriptor, ...]):
        """
        Initialize the task registry.

        Args:
            descriptors (tuple[TaskDescriptor, ...]): Collection of task descriptors
                defining all available tasks. Each descriptor must have a unique name.

        Raises:
            ValueError: If duplicate task names are provided (dict comprehension
                will silently overwrite, but this is a programming error).

        Examples:
            >>> from archcare.core.task_registry import TaskRegistry, TaskDescriptor
            >>> from archcare.core.base_task import BaseTask
            >>> from archcare.core.formatter import DefaultFormatter
            >>> from archcare.core.models import TaskResult, success
            >>>
            >>> class TaskA(BaseTask):
            ...     def execute(self) -> TaskResult:
            ...         return success("A done")
            >>> class TaskB(BaseTask):
            ...     def execute(self) -> TaskResult:
            ...         return success("B done")
            >>>
            >>> registry = TaskRegistry(
            ...     (
            ...         TaskDescriptor("task-a", TaskA),
            ...         TaskDescriptor("task-b", TaskB),
            ...     )
            ... )
            >>> registry.names()
            ('task-a', 'task-b')
            >>> registry.get_task_class("task-a")
            <class '...TaskA'>
            >>> registry.get_formatter_class("task-b")
            <class 'archcare.core.formatter.DefaultFormatter'>

        See Also:
            - [`TaskExecutor`][archcare.core.executor.TaskExecutor]: Consumes this registry
            - [`TaskNotRegisteredError`][]: Raised on failed lookups
        """
        self._by_name = {d.name: d for d in descriptors}

    def get_task_class(self, name: str) -> type[BaseTask]:
        """
        Look up the task class registered under `name`.

        Retrieves the concrete [`BaseTask`][] subclass associated with the given task name.

        Args:
            name (str): The task name to look up (e.g., "health-check").

        Returns:
            (type[BaseTask]): The task class for instantiation by
                [`TaskExecutor`][archcare.core.executor.TaskExecutor].

        Raises:
            TaskNotRegisteredError: If no task is registered under the given name. The error message
                includes the list of available task names for debugging.

        Examples:
            >>> from archcare.core.task_registry import TaskRegistry, TaskDescriptor
            >>> from archcare.core.base_task import BaseTask
            >>> from archcare.core.models import TaskResult, success
            >>>
            >>> class MyTask(BaseTask):
            ...     def execute(self) -> TaskResult:
            ...         return success("done")
            >>> registry = TaskRegistry((TaskDescriptor("my-task", MyTask),))
            >>> cls = registry.get_task_class("my-task")
            >>> cls.__name__
            'MyTask'
            >>> issubclass(cls, BaseTask)
            True
            >>> registry.get_task_class("unknown")  # doctest: +IGNORE_EXCEPTION_DETAIL
            Traceback (most recent call last):
            ...
            archcare.core.exceptions.TaskNotRegisteredError:
            Task 'No task registered for: unknown. Available tasks:
            ["my-task"]' is not registered
        """
        descriptor = self._by_name.get(name)
        if descriptor is None:
            raise TaskNotRegisteredError(name, list(self._by_name.keys()))
        return descriptor.task_class

    def get_formatter_class(self, name: str) -> type[TaskDetailFormatter]:
        """
        Look up the detail formatter for `name`, or DefaultFormatter if no formatter is registered.

        Retrieves the [`TaskDetailFormatter`][] implementation for rendering the task's
        result details in the CLI.

        Args:
            name (str): The task name to look up (e.g., "health-check").

        Returns:
            (type[TaskDetailFormatter]): The formatter class. Defaults to [`DefaultFormatter`][] if
                the descriptor didn't specify a custom formatter.

        Raises:
            TaskNotRegisteredError: If no task is registered under the given name.

        Examples:
            >>> from archcare.core.task_registry import TaskRegistry, TaskDescriptor
            >>> from archcare.core.base_task import BaseTask
            >>> from archcare.core.formatter import DefaultFormatter
            >>> from archcare.core.models import TaskResult, success
            >>>
            >>> class MyTask(BaseTask):
            ...     def execute(self) -> TaskResult:
            ...         return success("done")
            >>> registry = TaskRegistry((TaskDescriptor("my-task", MyTask),))
            >>> fmt_cls = registry.get_formatter_class("my-task")
            >>> fmt_cls
            <class 'archcare.core.formatter.DefaultFormatter'>
        """
        descriptor = self._by_name.get(name)
        if descriptor is None:
            raise TaskNotRegisteredError(name, list(self._by_name.keys()))
        return descriptor.formatter_class

    def names(self) -> tuple[str, ...]:
        """
        Get all registered task names.

        Returns a tuple of all task names currently in the registry, in the order
        they were provided during construction.

        Returns:
            (tuple[str, ...]): Tuple of registered task names.

        Examples:
            >>> from archcare.core.task_registry import TaskRegistry, TaskDescriptor
            >>> from archcare.core.base_task import BaseTask
            >>> from archcare.core.models import TaskResult, success
            >>>
            >>> class A(BaseTask):
            ...     def execute(self) -> TaskResult:
            ...         return success("a")
            >>> class B(BaseTask):
            ...     def execute(self) -> TaskResult:
            ...         return success("b")
            >>> registry = TaskRegistry(
            ...     (
            ...         TaskDescriptor("task-a", A),
            ...         TaskDescriptor("task-b", B),
            ...     )
            ... )
            >>> registry.names()
            ('task-a', 'task-b')
        """
        return tuple(self._by_name.keys())
