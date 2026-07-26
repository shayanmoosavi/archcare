"""
Unit tests for the `task` command group (cli/commands/task.py).

Commands are called as plain functions with a lightweight fake ctx, not
through Typer's CliRunner - CliRunner exercises Click's own argument
parsing, which belongs to a later integration-test pass, not here.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import typer

from archcare.cli.commands.task import list_tasks, run, status
from archcare.services.exceptions import (
    InvalidTasksFileError,
    InvalidTaskTypeError,
    TaskNotFoundError,
)

_MODULE = "archcare.cli.commands.task"

# ---------------------------------------------------------------------------
# Helpers and Fixtures
# ---------------------------------------------------------------------------


def _make_ctx(app_context=None) -> SimpleNamespace:
    """
    A minimal ctx stand-in exposing only .obj - a bare MagicMock() would
    silently accept a typo like ctx.obj2 without ever failing; this won't.
    """
    return SimpleNamespace(obj=app_context or MagicMock())


def _outcome(
    is_success: bool = False, is_partial: bool = False, is_skipped: bool = False
) -> MagicMock:
    outcome = MagicMock()
    outcome.is_success.return_value = is_success
    outcome.is_partial.return_value = is_partial
    outcome.is_skipped.return_value = is_skipped
    return outcome


@pytest.fixture
def mock_service(mocker) -> MagicMock:
    return mocker.patch(f"{_MODULE}.TaskService").return_value


@pytest.fixture
def mock_presenter(mocker) -> MagicMock:
    return mocker.patch(f"{_MODULE}.TaskPresenter").return_value


# ---------------------------------------------------------------------------
# task run
# ---------------------------------------------------------------------------


class TestRun:
    @pytest.mark.usefixtures("mock_presenter")
    def test_calls_setup_logging(self, mock_service: MagicMock):
        mock_service.run_task.return_value = MagicMock(outcome=_outcome(is_success=True))
        ctx = _make_ctx()

        with pytest.raises(typer.Exit):
            run(ctx, task_name="update-mirrorlist")  # ty:ignore[invalid-argument-type]

        ctx.obj.setup_logging.assert_called_once()

    @pytest.mark.usefixtures("mock_presenter")
    def test_service_called_with_task_name_and_force(self, mock_service: MagicMock):
        mock_service.run_task.return_value = MagicMock(outcome=_outcome(is_success=True))
        ctx = _make_ctx()

        with pytest.raises(typer.Exit):
            run(
                ctx,  # ty:ignore[invalid-argument-type]
                task_name="update-mirrorlist",
                force=True,
            )

        mock_service.run_task.assert_called_once_with("update-mirrorlist", True)

    def test_invalid_tasks_file_error_shows_empty_and_exits_1(
        self, mock_service: MagicMock, mock_presenter: MagicMock
    ):
        mock_service.run_task.side_effect = InvalidTasksFileError()
        ctx = _make_ctx()

        with pytest.raises(typer.Exit) as exc_info:
            run(ctx, task_name="update-mirrorlist")  # ty:ignore[invalid-argument-type]

        mock_presenter.empty.assert_called_once()
        assert exc_info.value.exit_code == 1

    def test_task_not_found_shows_not_found_and_exits_1(
        self, mock_service: MagicMock, mock_presenter: MagicMock
    ):
        mock_service.run_task.side_effect = TaskNotFoundError("bogus-task")
        ctx = _make_ctx()

        with pytest.raises(typer.Exit) as exc_info:
            run(ctx, task_name="bogus-task")  # ty:ignore[invalid-argument-type]

        mock_presenter.not_found.assert_called_once_with("bogus-task")
        assert exc_info.value.exit_code == 1

    def test_typer_abort_shows_aborted_and_exits_1(
        self, mock_service: MagicMock, mock_presenter: MagicMock
    ):
        mock_service.run_task.side_effect = typer.Abort()
        ctx = _make_ctx()

        with pytest.raises(typer.Exit) as exc_info:
            run(ctx, task_name="update-mirrorlist")  # ty:ignore[invalid-argument-type]

        mock_presenter.aborted.assert_called_once()
        assert exc_info.value.exit_code == 1

    def test_generic_exception_shows_error_and_exits_1(
        self, mock_service: MagicMock, mock_presenter: MagicMock
    ):
        mock_service.run_task.side_effect = Exception("disk on fire")
        ctx = _make_ctx()

        with pytest.raises(typer.Exit) as exc_info:
            run(ctx, task_name="update-mirrorlist")  # ty:ignore[invalid-argument-type]

        assert "update-mirrorlist" in mock_presenter.error.call_args.args[0]
        assert "disk on fire" in mock_presenter.error.call_args.args[0]
        assert exc_info.value.exit_code == 1

    @pytest.mark.parametrize(
        "flags",
        [
            {"is_success": True},
            {"is_partial": True},
            {"is_skipped": True},
        ],
    )
    def test_success_partial_or_skipped_exits_0(
        self, flags, mock_service: MagicMock, mock_presenter: MagicMock
    ):
        mock_service.run_task.return_value = MagicMock(outcome=_outcome(**flags))
        ctx = _make_ctx()

        with pytest.raises(typer.Exit) as exc_info:
            run(ctx, task_name="update-mirrorlist")  # ty:ignore[invalid-argument-type]

        assert exc_info.value.exit_code == 0
        mock_presenter.render_run.assert_called_once()

    @pytest.mark.usefixtures("mock_presenter")
    def test_failure_exits_1(self, mock_service: MagicMock):
        """
        The implicit 'else' branch: none of is_success/is_partial/
        is_skipped true means the task genuinely failed. Not guarded by
        its own except clause, so worth pinning down explicitly.
        """
        mock_service.run_task.return_value = MagicMock(outcome=_outcome())
        ctx = _make_ctx()

        with pytest.raises(typer.Exit) as exc_info:
            run(ctx, task_name="update-mirrorlist")  # ty:ignore[invalid-argument-type]

        assert exc_info.value.exit_code == 1

    def test_render_run_receives_settings_and_verbose(
        self, mock_service: MagicMock, mock_presenter: MagicMock
    ):
        mock_service.run_task.return_value = MagicMock(outcome=_outcome(is_success=True))
        ctx = _make_ctx()
        ctx.obj.settings = "SETTINGS_SENTINEL"

        with pytest.raises(typer.Exit):
            run(ctx, task_name="update-mirrorlist", verbose=True)  # ty:ignore[invalid-argument-type]

        _, kwargs = mock_presenter.render_run.call_args
        assert kwargs["settings"] == "SETTINGS_SENTINEL"
        assert kwargs["verbose"] is True


# ---------------------------------------------------------------------------
# task status
# ---------------------------------------------------------------------------


class TestStatus:
    def test_invalid_tasks_file_error_shows_empty_and_exits_1(
        self, mock_service: MagicMock, mock_presenter: MagicMock
    ):
        mock_service.get_task_status.side_effect = InvalidTasksFileError()
        ctx = _make_ctx()

        with pytest.raises(typer.Exit) as exc_info:
            status(ctx)  # ty:ignore[invalid-argument-type]

        mock_presenter.empty.assert_called_once()
        assert exc_info.value.exit_code == 1

    def test_task_not_found_shows_error_with_exception_message(
        self, mock_service: MagicMock, mock_presenter: MagicMock
    ):
        mock_service.get_task_status.side_effect = TaskNotFoundError("bogus-task")
        ctx = _make_ctx()

        with pytest.raises(typer.Exit) as exc_info:
            status(ctx, task_name="bogus-task")  # ty:ignore[invalid-argument-type]

        mock_presenter.not_found.assert_called_once_with("bogus-task")
        assert exc_info.value.exit_code == 1

    def test_generic_exception_shows_error_and_exits_1(
        self, mock_service: MagicMock, mock_presenter: MagicMock
    ):
        mock_service.get_task_status.side_effect = RuntimeError("CPU melted")
        ctx = _make_ctx()

        with pytest.raises(typer.Exit) as exc_info:
            status(ctx)  # ty:ignore[invalid-argument-type]

        assert "CPU melted" in mock_presenter.error.call_args.args[0]
        assert exc_info.value.exit_code == 1

    def test_service_called_with_task_name_and_due_only(
        self, mock_service: MagicMock, mock_presenter: MagicMock
    ):
        mock_service.get_task_status.return_value = "RESPONSE_SENTINEL"
        ctx = _make_ctx()

        status(
            ctx,  # ty:ignore[invalid-argument-type]
            task_name="update-mirrorlist",
            due_only=True,
        )

        mock_service.get_task_status.assert_called_once_with("update-mirrorlist", True)
        mock_presenter.render_status.assert_called_once_with("RESPONSE_SENTINEL")


# ---------------------------------------------------------------------------
# task list
# ---------------------------------------------------------------------------


class TestListTasks:
    def test_invalid_tasks_file_error_shows_empty_and_exits_1(
        self, mock_service: MagicMock, mock_presenter: MagicMock
    ):
        mock_service.list_tasks.side_effect = InvalidTasksFileError()
        ctx = _make_ctx()

        with pytest.raises(typer.Exit) as exc_info:
            list_tasks(ctx)  # ty:ignore[invalid-argument-type]

        mock_presenter.empty.assert_called_once()
        assert exc_info.value.exit_code == 1

    def test_invalid_task_type_shows_message_and_exits_1(
        self, mock_service: MagicMock, mock_presenter: MagicMock
    ):
        mock_service.list_tasks.side_effect = InvalidTaskTypeError("weekly")
        ctx = _make_ctx()

        with pytest.raises(typer.Exit) as exc_info:
            list_tasks(ctx, task_type="weekly")  # ty:ignore[invalid-argument-type]

        mock_presenter.invalid_task_type.assert_called_once()
        assert exc_info.value.exit_code == 1

    def test_service_called_with_task_type_and_renders_list(
        self, mock_service: MagicMock, mock_presenter: MagicMock
    ):
        mock_service.list_tasks.return_value = "RESPONSE_SENTINEL"
        ctx = _make_ctx()

        list_tasks(ctx, task_type="manual")  # ty:ignore[invalid-argument-type]

        mock_service.list_tasks.assert_called_once_with("manual")
        mock_presenter.render_list.assert_called_once_with("RESPONSE_SENTINEL")
