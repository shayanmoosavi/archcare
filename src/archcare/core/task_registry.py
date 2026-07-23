"""Task registry for the Archcare core layer."""

from dataclasses import dataclass

from archcare.tasks.base import BaseTask

from .exceptions import TaskNotRegisteredError
from .formatter import DefaultFormatter, TaskDetailFormatter


@dataclass(frozen=True)
class TaskDescriptor:
    """Static description of a single task: its name, execution class, and detail formatter."""

    name: str
    task_class: type[BaseTask]
    formatter_class: type[TaskDetailFormatter] = DefaultFormatter


class TaskRegistry:
    """
    Immutable, statically-defined mapping from task name to its execution
    class and detail formatter.
    """

    def __init__(self, descriptors: tuple[TaskDescriptor, ...]):
        self._by_name = {d.name: d for d in descriptors}

    def get_task_class(self, name: str) -> type[BaseTask]:
        """
        Look up the task class registered under `name`.

        Raises:
            TaskNotRegisteredError: If no task is registered under that name.
        """
        descriptor = self._by_name.get(name)
        if descriptor is None:
            raise TaskNotRegisteredError(
                f"No task registered for: {name}. "
                f"Available tasks: {list(self._by_name.keys())}"
            )
        return descriptor.task_class

    def get_formatter_class(self, name: str) -> type[TaskDetailFormatter]:
        """
        Look up the detail formatter for `name`, or DefaultFormatter if
        no formatter is registered.

        Raises:
            TaskNotRegisteredError: If no task is registered under that name.
        """
        descriptor = self._by_name.get(name)
        if descriptor is None:
            raise TaskNotRegisteredError(
                f"No task registered for: {name}. "
                f"Available tasks: {list(self._by_name.keys())}"
            )
        return descriptor.formatter_class

    def names(self) -> tuple[str, ...]:
        """All registered task names."""
        return tuple(self._by_name.keys())
