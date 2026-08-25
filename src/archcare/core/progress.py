"""
Progress reporting port for the Archcare core layer.

This module defines the progress reporting interface ([TaskProgress][]) and its
default null implementation ([NoOpProgress][]). It establishes the boundary (port)
between task execution in the core layer and user interface representation in the
CLI/presentation layer.

Tasks report real-time execution increments (e.g., individual steps or durations)
by interacting with a [TaskProgress][] instance. This allows the core engine to
remain agnostic of the terminal environment, while allowing CLI runners to plug
in rich, interactive displays (like spinners or determinate bars).

Key Concepts:
    - **Port**: The [TaskProgress][] protocol defines the interface that any progress
      reporter must implement.
    - **Adapter**: CLI progress reporting (e.g., using `rich.progress`) acts as an adapter
      implementing this port.
    - **No-Op Mode**: When running without an interactive TTY (e.g., in a systemd timer
      or testing environment), the system falls back to [NoOpProgress][].

See Also:
    - [TaskStep][]: The data structure representing progress increments.
    - [archcare.cli.progress][]: CLI-specific progress display implementation.
"""

from contextlib import AbstractContextManager, nullcontext
from typing import Protocol

from .models import TaskStep


class TaskProgress(Protocol):
    """
    Port through which tasks report step/duration progress during execution.

    This protocol specifies the interface for progress feedback. It accommodates both determinate
    operations (where the total number of steps is known) and indeterminate operations
    (where duration is unpredictable or steps are not quantifiable).

    By implementing this protocol, any GUI) can provide appropriate visual feedback during
    system maintenance tasks.

    Examples:
        Let's demonstrate how a class would conform to this protocol:

        >>> from contextlib import contextmanager, nullcontext, AbstractContextManager
        >>> from typing import Generator
        >>> from archcare.core.models import TaskStep, TaskStatus
        >>> from archcare.core.progress import TaskProgress
        >>>
        >>> class CustomProgress:
        ...     def start(self, total: int | None = None) -> None:
        ...         print(f"Started progress with total={total}")
        ...     def pause(self) -> AbstractContextManager[None]:
        ...         return nullcontext()
        ...     def advance(self, step: TaskStep) -> None:
        ...         print(f"Completed step: {step.name}")
        ...     @contextmanager
        ...     def spinner(self, label: str) -> Generator[None, None, None]:
        ...         print(f"Spinner active: {label}")
        ...         try:
        ...             yield
        ...         finally:
        ...             print("Spinner stopped")
        ...     def stop(self) -> None:
        ...         print("Progress stopped")
        >>>
        >>> # Ensure compliance with the TaskProgress protocol
        >>> progress: TaskProgress = CustomProgress()
        >>> progress.start(total=5)
        Started progress with total=5
        >>> step = TaskStep(name="Verify disk space", status=TaskStatus.SUCCESS)
        >>> progress.advance(step)
        Completed step: Verify disk space
        >>> progress.stop()
        Progress stopped

    See Also
        - [RichProgress][archcare.cli.progress.RichProgress]: CLI implementation of this protocol.
    """

    def start(self, total: int | None = None) -> None:
        """
        Begin a progress display.

        Initializes the progress display session. Depending on whether the total count of tasks
        is known, this will setup either a determinate bar or an indeterminate spinner/indicator.

        Args:
            total (int | None): Number of discrete steps if known (renders a determinate bar),
                or `None` if the work is a single unpredictable-duration operation (renders
                an indeterminate spinner instead). Defaults to `None`.

        See Also:
            [stop][]: Ends the progress display.
        """
        ...

    def pause(self) -> AbstractContextManager[None]:
        """
        Suspend the live display so a blocking prompt can render normally.

        Temporarily hides or pauses the progress bars/spinners. This context manager is critical
        for operations that require interactive user input, such as password prompts for `sudo`
        command execution, ensuring that the rendering of interactive prompts is not disrupted
        or overwritten by background progress updates.

        Returns:
            (AbstractContextManager[None]): A context manager within which the
                progress display is paused and will automatically resume upon exit.

        Examples:
            >>> from archcare.core.progress import NoOpProgress
            >>> progress = NoOpProgress()
            >>> with progress.pause():
            ...     print("Prompting for sudo password...")
            Prompting for sudo password...
        """
        ...

    def advance(self, step: TaskStep) -> None:
        """
        Record one completed step, advancing a determinate bar by one.

        Updates the progress display to reflect the completion of a specific task increment.
        In a CLI presenter, this typically increments the determinate percentage bar and
        updates status logs or messages on the screen.

        Args:
            step (TaskStep): The specific progress step that was completed, containing
                details like the step's name, status, and optional details.

        See Also:
            [TaskStep][]: The representation of a single progress increment.
        """
        ...

    def spinner(self, label: str) -> AbstractContextManager[None]:
        """
        Context manager wrapping a single unknown-duration operation.

        Provides visual feedback (typically an active spinner and label text) during
        the execution of a single long-running block whose duration is unpredictable.
        Upon exiting the block, the spinner is automatically cleaned up.

        Args:
            label (str): Text description to display next to the spinner
                (e.g., "Reflecting mirrors...").

        Returns:
            (AbstractContextManager[None]): A context manager that shows the spinner
                on enter and hides it on exit.

        Examples:
            >>> import time
            >>> from archcare.core.progress import NoOpProgress
            >>> progress = NoOpProgress()
            >>> with progress.spinner("Running system maintenance..."):
            ...     # perform maintenance work
            ...     pass
        """
        ...

    def stop(self) -> None:
        """
        Tear down the progress display, whatever state it's in.

        Cleans up and terminates the progress rendering session, ensuring
        terminals or interfaces return to their normal state and resources are released.
        This should always be called (typically in a `finally` block or handled automatically
        by runners) after `start()` has been called.

        See Also:
            [start][]: Begins the progress display.
        """
        ...


class NoOpProgress:
    """
    Default progress reporter used when none is supplied.

    This class serves as a "null object" or "no-op" implementation of the
    [TaskProgress][] protocol. It silently ignores all progress updates,
    which is appropriate for:

    - Unattended automated runs (e.g., systemd timers)
    - Command invocations without a connected interactive TTY
    - Unit and integration tests where progress rendering is unnecessary

    By implementing the same protocol as interactive progress bars, tasks can remain
    completely decoupled from environment details.

    Examples:
        >>> from archcare.core.progress import NoOpProgress
        >>> from archcare.core.models import TaskStep, TaskStatus
        >>> progress = NoOpProgress()
        >>> progress.start(total=10)
        >>> step = TaskStep(name="Check mirror latency", status=TaskStatus.SUCCESS)
        >>> progress.advance(step)
        >>> with progress.pause():
        ...     pass
        >>> with progress.spinner("Checking disks..."):
        ...     pass
        >>> progress.stop()

    See Also:
        [TaskProgress][]: Protocol describing the full progress interface.
    """

    def start(self, total: int | None = None) -> None:
        """
        Begin a progress display (no-op).

        Args:
            total (int | None): Number of discrete steps if known. Defaults to `None`.
        """
        pass

    def pause(self) -> AbstractContextManager[None]:
        """
        Suspend the live display (no-op).

        Returns:
            (AbstractContextManager[None]): A null context manager.
        """
        return nullcontext()

    def advance(self, step: TaskStep) -> None:
        """
        Record one completed step (no-op).

        Args:
            step (TaskStep): The completed progress step.
        """
        pass

    def spinner(self, label: str) -> AbstractContextManager[None]:
        """
        Context manager wrapping a single unknown-duration operation (no-op).

        Args:
            label (str): Text description for the spinner.

        Returns:
            AbstractContextManager[None]: A null context manager.
        """
        return nullcontext()

    def stop(self) -> None:
        """Tear down the progress display (no-op)."""
        pass
