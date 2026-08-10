"""Progress reporting port for the Archcare core layer."""

from contextlib import AbstractContextManager, nullcontext
from typing import Protocol

from .models import TaskStep


class TaskProgress(Protocol):
    """Port through which tasks report step/duration progress during execution."""

    def start(self, total: int | None = None) -> None:
        """
        Begin a progress display.

        Args:
            total: Number of discrete steps if known (renders a determinate
                bar), or None if the work is a single unpredictable-duration
                operation (renders an indeterminate spinner instead).
        """
        ...

    def pause(self) -> AbstractContextManager[None]:
        """Suspend the live display so a blocking prompt (e.g. sudo) can render normally."""
        ...

    def advance(self, step: TaskStep) -> None:
        """Record one completed step, advancing a determinate bar by one."""
        ...

    def spinner(self, label: str) -> AbstractContextManager[None]:
        """Context manager wrapping a single unknown-duration operation."""
        ...

    def stop(self) -> None:
        """Tear down the progress display, whatever state it's in."""
        ...


class NoOpProgress:
    """
    Default progress reporter used when none is supplied (tests, systemd
    runs, any caller without a TTY to render into).
    """

    def start(self, total: int | None = None) -> None:
        pass

    def pause(self) -> AbstractContextManager[None]:
        return nullcontext()

    def advance(self, step: TaskStep) -> None:
        pass

    def spinner(self, label: str) -> AbstractContextManager[None]:
        return nullcontext()

    def stop(self) -> None:
        pass
