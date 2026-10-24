"""Unit tests for the CLI's RichProgress adapter."""

from io import StringIO
from unittest.mock import MagicMock

import pytest
from _pytest.capture import CaptureFixture
from rich.console import Console

from archcare.cli.progress import RichProgress
from archcare.config import TaskStatus
from archcare.core import TaskStep

_MODULE = "archcare.cli.progress"


@pytest.fixture
def mock_progress_class(mocker) -> MagicMock:
    """Patch the underlying rich.progress.Progress class."""
    return mocker.patch(f"{_MODULE}.Progress")


@pytest.fixture
def rich_progress(mock_progress_class: MagicMock) -> RichProgress:
    return RichProgress()


class TestConstruction:
    def test_constructs_a_single_progress_instance(
        self, mock_progress_class: MagicMock, rich_progress: RichProgress
    ):
        mock_progress_class.assert_called_once()
        assert rich_progress._task_id is None

    def test_console_is_plumbed_into_the_rich_progress(self, mock_progress_class: MagicMock):
        """
        The injection seam the prompt-guard tests rely on: a caller-provided console must reach
        the underlying Rich progress unchanged.
        """
        console = Console(file=StringIO())

        RichProgress(console=console)

        mock_progress_class.assert_called_once()
        assert mock_progress_class.call_args.kwargs["console"] is console

    def test_console_defaults_to_none(self, mock_progress_class: MagicMock):
        """
        `cli/context.py` constructs `RichProgress()` with no args — the default path
        must keep handing Rich its standard terminal console.
        """
        RichProgress()

        mock_progress_class.assert_called_once()
        assert mock_progress_class.call_args.kwargs["console"] is None


class TestStart:
    def test_starts_the_live_display_and_adds_a_task(self, rich_progress: RichProgress):
        mock_progress: MagicMock = rich_progress._progress  # ty:ignore[invalid-assignment]

        rich_progress.start(total=5)

        mock_progress.start.assert_called_once()
        mock_progress.add_task.assert_called_once_with("Working...", total=5)
        assert rich_progress._task_id is mock_progress.add_task.return_value
        rich_progress.stop()

    def test_total_none_still_adds_a_task(self, rich_progress: RichProgress):
        """
        total=None is the indeterminate case - Rich itself decides how to render it,
        RichProgress just has to pass it through unchanged.
        """
        mock_progress: MagicMock = rich_progress._progress  # ty:ignore[invalid-assignment]

        rich_progress.start(total=None)

        mock_progress.add_task.assert_called_once_with("Working...", total=None)
        rich_progress.stop()


class TestPause:
    def test_stops_before_body_and_restarts_after(self, rich_progress: RichProgress):
        mock_progress: MagicMock = rich_progress._progress  # ty:ignore[invalid-assignment]
        rich_progress.start(total=5)
        mock_progress.reset_mock()  # isolate pause()'s own calls from start()'s

        with rich_progress.pause():
            # Rich's own Live must be stopped by now so a tty prompt (e.g.
            # sudo) can render without the auto-refresh thread overwriting it
            mock_progress.stop.assert_called_once()
            mock_progress.start.assert_not_called()

        mock_progress.start.assert_called_once()
        rich_progress.stop()

    def test_resumes_even_if_body_raises(self, rich_progress: RichProgress):
        mock_progress: MagicMock = rich_progress._progress  # ty:ignore[invalid-assignment]

        with pytest.raises(RuntimeError), rich_progress.pause():
            raise RuntimeError("sudo prompt handling failed")

        mock_progress.start.assert_called_once()
        rich_progress.stop()


class TestAdvance:
    def test_updates_the_active_task_by_one(self, rich_progress: RichProgress):
        mock_progress: MagicMock = rich_progress._progress  # ty:ignore[invalid-assignment]
        rich_progress.start(total=3)
        step = TaskStep(name="Disk space", status=TaskStatus.SUCCESS)

        rich_progress.advance(step)

        mock_progress.update.assert_called_once_with(
            rich_progress._task_id, advance=1, description=str(step)
        )
        rich_progress.stop()

    def test_noop_when_start_was_never_called(self, rich_progress: RichProgress):
        """FailedServicesTask never calls start() - advance() must not
        explode if it were ever called without one."""
        mock_progress: MagicMock = rich_progress._progress  # ty:ignore[invalid-assignment]
        step = TaskStep(name="x", status=TaskStatus.SUCCESS)

        rich_progress.advance(step)

        mock_progress.update.assert_not_called()
        rich_progress.stop()


class TestStop:
    def test_stops_the_live_display_and_clears_task_id(self, rich_progress: RichProgress):
        mock_progress: MagicMock = rich_progress._progress  # ty:ignore[invalid-assignment]
        rich_progress.start(total=1)

        rich_progress.stop()

        mock_progress.stop.assert_called_once()
        assert rich_progress._task_id is None

    def test_safe_to_call_without_a_prior_start(self, rich_progress: RichProgress):
        """This is the exact path BaseTask.run()'s finally block exercises
        for tasks that never report progress at all."""
        rich_progress.stop()  # must not raise

        rich_progress._progress.stop.assert_called_once()  # ty:ignore[unresolved-attribute]


class TestSpinner:
    def test_adds_and_removes_an_indeterminate_task_around_the_body(
        self, rich_progress: RichProgress
    ):
        mock_progress: MagicMock = rich_progress._progress  # ty:ignore[invalid-assignment]

        with rich_progress.spinner("Running reflector..."):
            body_ran = True
            mock_progress.add_task.assert_called_once_with("Running reflector...", total=None)

        assert body_ran
        mock_progress.remove_task.assert_called_once_with(mock_progress.add_task.return_value)
        mock_progress.stop.assert_called_once()

    def test_removes_task_and_stops_even_if_body_raises(self, rich_progress: RichProgress):
        mock_progress: MagicMock = rich_progress._progress  # ty:ignore[invalid-assignment]

        with pytest.raises(RuntimeError), rich_progress.spinner("label"):
            raise RuntimeError("reflector failed")

        mock_progress.remove_task.assert_called_once()
        mock_progress.stop.assert_called_once()

    def test_leaves_a_render_it_did_not_start_untouched(self, rich_progress: RichProgress):
        """
        Ownership contract: a spinner entered while the main bar's render is showing removes
        only its own task on exit and must not stop the bar — that teardown is exactly what
        used to darken system-update's display before its post-query pause brackets.
        """
        mock_progress: MagicMock = rich_progress._progress  # ty:ignore[invalid-assignment]
        rich_progress.start(total=5)
        mock_progress.reset_mock()  # isolate spinner()'s own calls from start()'s

        with rich_progress.spinner("label"):
            pass

        mock_progress.remove_task.assert_called_once()
        mock_progress.stop.assert_not_called()
        rich_progress.stop()


@pytest.fixture
def real_progress() -> RichProgress:
    """
    An adapter over the REAL Rich Progress, rendering into a string buffer.

    `is_live` cannot be tested against the class-mocked fixture above: every liveness
    question would be answered with a MagicMock. The prompt-guard harness reads this
    property at every guarded launch, so the transitions below are its contract.
    """
    return RichProgress(console=Console(file=StringIO()))


class TestIsLive:
    def test_false_before_any_display(self, real_progress: RichProgress):
        assert real_progress.is_live is False

    def test_true_between_start_and_stop(self, real_progress: RichProgress):
        real_progress.start(total=3)
        assert real_progress.is_live is True

        real_progress.stop()
        assert real_progress.is_live is False

    def test_false_inside_a_pause_bracket_and_true_after(self, real_progress: RichProgress):
        """A pause bracket is exactly the window guarded commands may run inside."""
        real_progress.start(total=3)

        with real_progress.pause():
            assert real_progress.is_live is False

        assert real_progress.is_live is True
        real_progress.stop()

    def test_pause_exit_marks_live_even_without_a_prior_start(self, real_progress: RichProgress):
        """
        The documented quirk the guard relies on: `pause()` restarts the render unconditionally, so
        a first pause taken while nothing was rendering still leaves the display live afterwards.
        """
        with real_progress.pause():
            assert real_progress.is_live is False

        assert real_progress.is_live is True
        real_progress.stop()

    def test_spinner_body_is_live_and_teardown_is_not(self, real_progress: RichProgress):
        with real_progress.spinner("Checking for AUR updates"):
            assert real_progress.is_live is True

        assert real_progress.is_live is False
        real_progress.stop()

    def test_spinner_leaves_a_running_bar_live(self, real_progress: RichProgress):
        """
        The ownership contract behind system-update's pause brackets: a spinner entered with
        the bar rendering removes only its own line, so the display is still live after the
        query spinners and the next pause bracket has a live render to stop — with the old
        full teardown the backup step found a dark display and its pause was unobservable.
        """
        real_progress.start(total=3)

        with real_progress.spinner("Checking for AUR updates"):
            assert real_progress.is_live is True

        assert real_progress.is_live is True
        real_progress.stop()
        assert real_progress.is_live is False

    def test_renders_nothing_to_the_real_stdout(
        self, real_progress: RichProgress, capsys: CaptureFixture[str]
    ):
        """
        The whole point of the console seam: a full start → pause → spinner → stop cycle must not
        leak a single byte of escape codes onto the runner's stdout.
        """
        real_progress.start(total=3)
        with real_progress.pause():
            pass
        with real_progress.spinner("working"):
            pass
        real_progress.stop()

        assert capsys.readouterr().out == ""
