"""
Formatter port for the Archcare core layer.

This module defines the task details formatting interface ([TaskDetailFormatter][])
and its default fallback implementation ([DefaultFormatter][]). It establishes the boundary
(port) between the core execution results and the presentation layer, allowing task details
(structured dataclasses returned by task execution) to be formatted in a human-readable layout.

Instead of tasks deciding how to print themselves to stdout (violating separation of concerns),
each task registers a companion [TaskDetailFormatter][] implementation in the CLI layer.
If no custom formatter is registered for a task, the framework gracefully falls back to the
generic [DefaultFormatter][].

Key Concepts:
    - **Port**: The [TaskDetailFormatter][] protocol defines the interface for converting
        task-specific detail models into readable text lines.
    - **Default Formatting**: The [DefaultFormatter][] inspects the detail object at runtime.
        If it is a dataclass, it prints public fields. Otherwise, it prints
        the string representation.

See Also:
    - [TaskResult][]: Contains the details formatted by this port.
    - [archcare.core.task_details][]: Task detail models returned by task execution.
    - [archcare.cli.presenters][]: Presenter implementations for various tasks in Archcare.
"""

import dataclasses
from typing import Any, Protocol


class TaskDetailFormatter(Protocol):
    """
    Port through which the presentation layer renders a task's execution details.

    This protocol specifies the interface used by CLI/GUI presenters to render
    rich details produced by a task execution. Details are typically task-specific,
    structured dataclasses containing metrics, service lists, or backup paths.

    Examples:
        >>> from dataclasses import dataclass
        >>> from archcare.core.formatter import TaskDetailFormatter
        >>>
        >>> @dataclass
        ... class DummyDetails:
        ...     count: int
        ...     status: str
        >>>
        >>> class DummyFormatter:
        ...     def format(self, details: DummyDetails) -> list[str]:
        ...         return [
        ...             f"Executed count: {details.count}",
        ...             f"Final status: {details.status}"
        ...         ]
        >>>
        >>> # Ensure compliance with the TaskDetailFormatter protocol
        >>> formatter: TaskDetailFormatter = DummyFormatter()
        >>> details = DummyDetails(count=42, status="healthy")
        >>> formatter.format(details)
        ['Executed count: 42', 'Final status: healthy']

    See Also:
        [DefaultFormatter][]: Default generic formatter.
    """

    def format(self, details: Any) -> list[str]:
        """
        Convert a task's details object into formatted output lines.

        Processes the task-specific details structured data model and compiles it
        into a sequence of descriptive, human-readable lines.

        Args:
            details (Any): The task-specific details object (usually a frozen
                dataclass) containing the fine-grained results of a task's execution.

        Returns:
            (list[str]): A list of strings, with each element representing a line
                of formatted output ready to be printed or rendered.
        """
        ...


class DefaultFormatter:
    """
    Default formatter used when a task has no dedicated formatter registered.

    This class serves as a fallback implementation of the [TaskDetailFormatter][] protocol.
    If a task execution returns a detail object but no dedicated custom formatter is
    registered, this fallback formatter will inspect the object:

    - If `details` is `None`, it returns an empty list.
    - If `details` is a dataclass, it returns a key-value dump of all public attributes
      (attributes that do not start with `_`).
    - Otherwise, it falls back to printing the standard string representation of the object.

    Examples:
        Format a dataclass:
        >>> from dataclasses import dataclass
        >>> from archcare.core.formatter import DefaultFormatter
        >>>
        >>> @dataclass
        ... class SimpleDetails:
        ...     cpu_usage: float
        ...     memory_usage: float
        ...     _internal: int = 100
        >>>
        >>> formatter = DefaultFormatter()
        >>> details = SimpleDetails(cpu_usage=25.5, memory_usage=68.2)
        >>> formatter.format(details)
        ['  cpu_usage: 25.5', '  memory_usage: 68.2']

        Format a plain string:

        >>> formatter.format("Just a generic detail message")
        ['  Just a generic detail message']

        Format None:

        >>> formatter.format(None)
        []

    See Also:
        [TaskDetailFormatter][]: Protocol for custom detail formatters.
    """

    def format(self, details: Any) -> list[str]:
        """
        Convert a task's details object into formatted lines using generic fallback logic.

        Args:
            details (Any): The detail object to format.

        Returns:
            (list[str]): Formatted text lines.
        """
        if details is None:
            return []
        if dataclasses.is_dataclass(details):
            return [
                f"  {f.name}: {getattr(details, f.name)}"
                for f in dataclasses.fields(details)
                if not f.name.startswith("_")
            ]
        return [f"  {details}"]
