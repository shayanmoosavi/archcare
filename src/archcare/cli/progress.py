"""
CLI adapter for [`TaskExecutor`][archcare.core.executor.TaskExecutor]'s progress port.

Wires [`TaskProgress`][archcare.core.progress.TaskProgress]'s `start()`, `advance()`, `spinner()`,
and `stop()` calls to a single Rich `Progress` instance — `total=None` renders as a spinner +
elapsed time, `total=N` renders as a determinate bar, so one widget covers both cases.

See Also:
    - [`TaskProgress`][archcare.core.progress.TaskProgress]: The port this adapter implements
    - [`TaskExecutor`][archcare.core.executor.TaskExecutor]: Primary consumer, reporting task step
        progress during runs
"""

from collections.abc import Generator
from contextlib import contextmanager

from rich.console import Console
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
    """
    Terminal implementation of [`TaskProgress`][archcare.core.progress.TaskProgress] built on a
    single Rich `Progress` instance.

    Supports two display modes: a determinate bar (when `start()` is given a step `total`) and an
    indeterminate spinner (via the `spinner()` context manager). The bar's description updates
    as steps advance.
    """

    def __init__(self, console: Console | None = None) -> None:
        """
        Initialize the progress adapter.

        Builds the Rich `Progress` widget with spinner, description, bar, percentage, and
        elapsed-time columns; no rendering starts until `start()` or `spinner()`.

        Args:
            console (Console | None): Console to render against. Tests inject a
                non-terminal console (`Console(file=StringIO())`) so a live render can
                never write escape codes to the real stdout; `None` — the default used by
                `cli.context` — hands Rich its standard terminal console.
        """
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
        )
        self._task_id: TaskID | None = None

    def start(self, total: int | None = None) -> None:
        """
        Start the main progress bar.

        Args:
            total (int | None): Number of steps to complete. When `None`, the bar renders as an
                indeterminate spinner. Defaults to `None`.

        Side Effects:
            Starts live terminal rendering of the progress widget.
        """
        self._progress.start()
        self._task_id = self._progress.add_task("Working...", total=total)

    @contextmanager
    def pause(self) -> Generator[None]:
        """
        Temporarily stop the progress display to yield the terminal.

        Use around prompts or other terminal output so the live progress
        bar doesn't clobber them; rendering resumes on exit.

        Yields:
            None: Nothing; used purely for the stop/start lifecycle.

        Note:
            Calls the underlying Rich `Progress`'s `stop()`/`start()` directly rather than the
            adapter's methods, to avoid clearing the progress bar from the terminal and starting
            a new one.
        """
        # Uses _progress.stop()/start() rather than the adaptor's methods
        # to avoid clearing the progress bar from the terminal and starting a new one.
        self._progress.stop()
        try:
            yield
        finally:
            self._progress.start()

    def advance(self, step: TaskStep) -> None:
        """
        Advance the main bar by one step and relabel it.

        Args:
            step (TaskStep): The step that just completed; its name becomes the bar's description.
                No-op when the bar isn't running.
        """
        if self._task_id is not None:
            self._progress.update(self._task_id, advance=1, description=str(step))

    @contextmanager
    def spinner(self, label: str) -> Generator[None]:
        """
        Run an indeterminate spinner for the duration of the block.

        Independent of the main bar: starts a fresh render, shows a spinner with the given label,
        and tears everything down on exit (including on exceptions).

        Args:
            label (str): Text shown next to the spinner.

        Yields:
            None: Nothing; used purely for the display lifecycle.
        """
        self._progress.start()
        task_id = self._progress.add_task(label, total=None)
        try:
            yield
        finally:
            self._progress.remove_task(task_id)
            self._progress.stop()

    def stop(self) -> None:
        """
        Stop the main progress bar and clear its handle.

        Side Effects:
            Removes the live progress widget from the terminal.
        """
        self._progress.stop()
        self._task_id = None

    @property
    def is_live(self) -> bool:
        """
        Report whether the underlying Rich live render is currently active.

        True while a bar started by `start()` or a `spinner()` body is running — and also
        after a `pause()` body exits, because `pause()` restarts the render
        unconditionally, even when nothing had been rendering when the bracket was
        entered. That restart is the semantic the prompt-guard test harness depends on:
        leaving any pause bracket means the display is live again.

        Returns:
            bool: `True` while Rich's `Live` is started, `False` otherwise.
        """
        return self._progress.live.is_started
