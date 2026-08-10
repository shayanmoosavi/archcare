"""
CLI adapter for TaskExecutor's progress port.

Wires TaskProgress's start()/advance()/spinner()/stop() calls to a single
Rich Progress instance - total=None renders as a spinner + elapsed time,
total=N renders as a determinate bar, so one widget covers both cases.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from archcare.core import TaskStep


class RichProgress:
    """Terminal implementation of `archcare.core.progress.TaskProgress`."""

    def __init__(self) -> None:
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
        )
        self._task_id: TaskID | None = None

    def start(self, total: int | None = None) -> None:
        self._progress.start()
        self._task_id = self._progress.add_task("Working...", total=total)

    @contextmanager
    def pause(self) -> Iterator[None]:
        # Uses _progress.stop()/start() rather than the adaptor's methods
        # to avoid clearing the progress bar from the terminal and starting a new one.
        self._progress.stop()
        try:
            yield
        finally:
            self._progress.start()

    def advance(self, step: TaskStep) -> None:
        if self._task_id is not None:
            self._progress.update(self._task_id, advance=1, description=str(step))

    @contextmanager
    def spinner(self, label: str) -> Iterator[None]:
        self._progress.start()
        task_id = self._progress.add_task(label, total=None)
        try:
            yield
        finally:
            self._progress.remove_task(task_id)
            self._progress.stop()

    def stop(self) -> None:
        self._progress.stop()
        self._task_id = None
