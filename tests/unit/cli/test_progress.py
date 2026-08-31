"""Unit tests for the CLI's RichProgress adapter."""

from unittest.mock import MagicMock

import pytest

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


class TestStart:
    def test_starts_the_live_display_and_adds_a_task(self, rich_progress: RichProgress):
        mock_progress: MagicMock = rich_progress._progress  # ty:ignore[invalid-assignment]

        rich_progress.start(total=5)

        mock_progress.start.assert_called_once()
        mock_progress.add_task.assert_called_once_with("Working...", total=5)
        assert rich_progress._task_id is mock_progress.add_task.return_value

    def test_total_none_still_adds_a_task(self, rich_progress: RichProgress):
        """total=None is the indeterminate case - Rich itself decides how to
        render it, RichProgress just has to pass it through unchanged."""
        mock_progress: MagicMock = rich_progress._progress  # ty:ignore[invalid-assignment]

        rich_progress.start(total=None)

        mock_progress.add_task.assert_called_once_with("Working...", total=None)


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

    def test_resumes_even_if_body_raises(self, rich_progress: RichProgress):
        mock_progress: MagicMock = rich_progress._progress  # ty:ignore[invalid-assignment]

        with pytest.raises(RuntimeError):
            with rich_progress.pause():
                raise RuntimeError("sudo prompt handling failed")

        mock_progress.start.assert_called_once()


class TestAdvance:
    def test_updates_the_active_task_by_one(self, rich_progress: RichProgress):
        mock_progress: MagicMock = rich_progress._progress  # ty:ignore[invalid-assignment]
        rich_progress.start(total=3)
        step = TaskStep(name="Disk space", status=TaskStatus.SUCCESS)

        rich_progress.advance(step)

        mock_progress.update.assert_called_once_with(
            rich_progress._task_id, advance=1, description=str(step)
        )

    def test_noop_when_start_was_never_called(self, rich_progress: RichProgress):
        """FailedServicesTask never calls start() - advance() must not
        explode if it were ever called without one."""
        mock_progress: MagicMock = rich_progress._progress  # ty:ignore[invalid-assignment]
        step = TaskStep(name="x", status=TaskStatus.SUCCESS)

        rich_progress.advance(step)

        mock_progress.update.assert_not_called()


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

        with pytest.raises(RuntimeError):
            with rich_progress.spinner("label"):
                raise RuntimeError("reflector failed")

        mock_progress.remove_task.assert_called_once()
        mock_progress.stop.assert_called_once()
