"""Unit tests for TaskPresenter."""

from typing import Any
from unittest.mock import MagicMock, Mock

import pytest

from archcare.cli.presenters.task_presenter import TaskPresenter
from archcare.config import AppSettings, TaskConfig, TaskStatus
from archcare.config.models import MaintenanceCheckSettings
from archcare.core import TaskResult, TaskScheduleInfo
from archcare.services.responses import (
    TaskListResponse,
    TaskRunResponse,
    TaskStatusResponse,
)

_MODULE = "archcare.cli.presenters.task_presenter"

_PATCH_INFO = f"{_MODULE}.print_info"
_PATCH_WARNING = f"{_MODULE}.print_warning"

# ---------------------------------------------------------------------------
# Fixtures and Helpers
# ---------------------------------------------------------------------------


def _make_outcome(
    is_skipped: bool = False, details: dict[str, Any] | None = None
) -> Mock:
    """A minimal TaskResult stand-in exposing only what TaskPresenter reads."""
    outcome = Mock(spec=TaskResult)
    outcome.is_skipped.return_value = is_skipped
    outcome.details = details or {}
    return outcome


def _make_result(
    status: TaskStatus = TaskStatus.SUCCESS,
    message: str = "did the thing",
    duration_seconds: float = 1.234,
    error: str | None = None,
    details: dict[str, Any] | None = None,
) -> Mock:
    """A minimal TaskResult stand-in exposing only what _format_task_details reads."""
    result = Mock(spec=TaskResult)
    result.status = status
    result.message = message
    result.duration_seconds = duration_seconds
    result.error = error
    result.details = details or {}
    return result


@pytest.fixture
def settings_terminal_mode() -> AppSettings:
    return AppSettings(
        maintenance_check=MaintenanceCheckSettings(
            output_mode="terminal", require_acknowledgment=True
        )
    )


@pytest.fixture
def settings_file_mode() -> AppSettings:
    return AppSettings(maintenance_check=MaintenanceCheckSettings(output_mode="file"))


@pytest.fixture
def mock_info(mocker) -> MagicMock:
    return mocker.patch(_PATCH_INFO)


@pytest.fixture(autouse=True)
def mock_header(mocker) -> MagicMock:
    return mocker.patch(f"{_MODULE}.print_header")


@pytest.fixture(autouse=True)
def mock_print_panel(mocker) -> MagicMock:
    return mocker.patch(f"{_MODULE}.print_panel")


@pytest.fixture(autouse=True)
def mock_console(mocker) -> MagicMock:
    return mocker.patch(f"{_MODULE}.console")


# ---------------------------------------------------------------------------
# render_run
# ---------------------------------------------------------------------------


class TestRenderRun:
    @pytest.fixture(autouse=True)
    def mock_format_details(self, mocker) -> MagicMock:
        return mocker.patch.object(TaskPresenter, "_format_task_details")

    @pytest.fixture
    def mock_mc_presenter(self, mocker) -> MagicMock:
        return mocker.patch(f"{_MODULE}.MaintenanceCheckPresenter")

    def test_header_shown_when_outcome_not_skipped(
        self, settings_terminal_mode: AppSettings, mock_header: MagicMock
    ):

        response = TaskRunResponse(
            task_name="update-mirrorlist",
            outcome=_make_outcome(is_skipped=False),
            is_interactive=True,
        )
        TaskPresenter.render_run(response, settings_terminal_mode)

        mock_header.assert_called_once_with(f"Running Task: {response.task_name}")

    def test_header_skipped_when_outcome_is_skipped(
        self, settings_terminal_mode: AppSettings, mock_header: MagicMock
    ):

        response = TaskRunResponse(
            task_name="update-mirrorlist",
            outcome=_make_outcome(is_skipped=True),
            is_interactive=True,
        )
        TaskPresenter.render_run(response, settings_terminal_mode)

        mock_header.assert_not_called()

    def test_renders_maintenance_table_when_result_present_and_not_file_mode(
        self, settings_terminal_mode: AppSettings, mocker, mock_mc_presenter: MagicMock
    ):
        mocker.patch(_PATCH_INFO)

        sentinel_result = object()
        response = TaskRunResponse(
            task_name="maintenance-check",
            outcome=_make_outcome(details={"maintenance_result": sentinel_result}),
            is_interactive=True,
        )
        TaskPresenter.render_run(response, settings_terminal_mode)

        mock_mc_presenter.render.assert_called_once_with(
            sentinel_result, is_interactive=True, require_acknowledgment=True
        )

    def test_shows_file_mode_message_instead_of_table(
        self,
        settings_file_mode: AppSettings,
        mock_info: MagicMock,
        mock_mc_presenter: MagicMock,
    ):
        """
        output_mode='file' must skip the table entirely and print a
        pointer to the report file instead - the message dynamically
        reflects settings.report_dir rather than a hardcoded path, so
        this stays portable across machines/CI.
        """

        response = TaskRunResponse(
            task_name="maintenance-check",
            outcome=_make_outcome(details={"maintenance_result": object()}),
            is_interactive=True,
        )
        TaskPresenter.render_run(response, settings_file_mode)

        mock_mc_presenter.render.assert_not_called()
        mock_info.assert_called_once()
        assert str(settings_file_mode.report_dir) in mock_info.call_args.args[0]

    def test_no_maintenance_rendering_when_maintenance_result_absent(
        self,
        settings_terminal_mode: AppSettings,
        mock_info: MagicMock,
        mock_mc_presenter: MagicMock,
    ):

        response = TaskRunResponse(
            task_name="failed-services",
            outcome=_make_outcome(details={}),
            is_interactive=True,
        )
        TaskPresenter.render_run(response, settings_terminal_mode)

        mock_mc_presenter.render.assert_not_called()
        mock_info.assert_not_called()

    @pytest.mark.parametrize("verbose", [True, False])
    def test_verbose_flag_carries_through(
        self,
        settings_terminal_mode: AppSettings,
        mock_format_details: MagicMock,
        verbose: bool,
    ):

        outcome = _make_outcome(details={})
        response = TaskRunResponse(
            task_name="health-check", outcome=outcome, is_interactive=True
        )
        TaskPresenter.render_run(response, settings_terminal_mode, verbose=verbose)

        mock_format_details.assert_called_once_with("health-check", outcome, verbose)


# ---------------------------------------------------------------------------
# render_status
# ---------------------------------------------------------------------------


class TestRenderStatus:
    @pytest.fixture(autouse=True)
    def mock_table(self, mocker) -> MagicMock:
        return mocker.patch.object(TaskPresenter, "_print_schedule_table")

    @pytest.fixture
    def mock_success(self, mocker) -> MagicMock:
        return mocker.patch(f"{_MODULE}.print_success")

    def test_due_only_with_no_schedule_shows_success_and_returns_early(
        self, mock_success: MagicMock, mock_table: MagicMock
    ):
        response = TaskStatusResponse(schedule_info=[], due_only=True)
        TaskPresenter.render_status(response)

        mock_success.assert_called_once_with("No tasks currently due!")
        mock_table.assert_not_called()

    def test_due_only_with_results_shows_table_not_success(
        self, mock_success: MagicMock, mock_table: MagicMock
    ):

        mock_task_info = MagicMock(spec=TaskScheduleInfo)
        response = TaskStatusResponse(schedule_info=[mock_task_info], due_only=True)
        TaskPresenter.render_status(response)

        mock_table.assert_called_once_with(response)
        mock_success.assert_not_called()

    def test_non_due_only_with_empty_schedule_still_shows_table(
        self, mock_success: MagicMock, mock_table: MagicMock
    ):
        response = TaskStatusResponse(schedule_info=[], due_only=False)
        TaskPresenter.render_status(response)

        mock_table.assert_called_once_with(response)
        mock_success.assert_not_called()

    def test_summary_panel_rendered_when_summary_present(
        self, mock_print_panel: MagicMock
    ):

        summary = {"total": 3, "overdue": 1}
        response = TaskStatusResponse(
            schedule_info=[MagicMock(spec=TaskScheduleInfo)], summary=summary
        )
        TaskPresenter.render_status(response)
        # Convert dict to panel content
        lines = [
            f"[bold]{key.replace('_', ' ').title()}:[/bold] {value}"
            for key, value in response.summary.items()  # ty:ignore[unresolved-attribute]
        ]
        mock_print_panel.assert_called_once_with("Summary", "\n".join(lines))

    def test_summary_panel_not_rendered_when_no_summary(
        self, mock_print_panel: MagicMock
    ):

        response = TaskStatusResponse(
            schedule_info=[MagicMock(spec=TaskScheduleInfo)], summary=None
        )
        TaskPresenter.render_status(response)

        mock_print_panel.assert_not_called()


# ---------------------------------------------------------------------------
# render_list
# ---------------------------------------------------------------------------


class TestRenderList:
    def test_shows_header_regardless_of_content(self, mocker, mock_header: MagicMock):
        mocker.patch(_PATCH_WARNING)

        TaskPresenter.render_list(TaskListResponse(tasks={}, filtered_by=None))

        mock_header.assert_called_once_with("Available Tasks")

    def test_empty_tasks_shows_warning_and_returns(
        self, mocker, mock_console: MagicMock
    ):
        mock_warning: MagicMock = mocker.patch(_PATCH_WARNING)

        TaskPresenter.render_list(TaskListResponse(tasks={}, filtered_by=None))

        mock_warning.assert_called_once_with("No tasks found!")
        mock_console.print.assert_not_called()

    @pytest.mark.parametrize(
        "task_fixture,expected_icon",
        [
            ("automated_task", "✓"),
            ("disabled_task", "✗"),
        ],
    )
    def test_tasks_use_correct_icon(
        self, task_fixture, expected_icon, request, mock_console: MagicMock
    ):

        task: TaskConfig = request.getfixturevalue(task_fixture)
        response = TaskListResponse(tasks={task.name: task}, filtered_by=None)
        TaskPresenter.render_list(response)

        first_line: MagicMock = mock_console.print.call_args_list[0].args[0]
        assert expected_icon in first_line
        assert task.name in first_line

    def test_console_print_called_thrice_per_task(
        self, automated_task: TaskConfig, mock_console: MagicMock
    ):
        """
        Pins down the name-line + description-line + blank-line structure, so a future
        refactor collapsing them into one print() silently drops the
        description without any test noticing.
        """

        response = TaskListResponse(
            tasks={automated_task.name: automated_task}, filtered_by=None
        )
        TaskPresenter.render_list(response)

        assert mock_console.print.call_count == 3
        assert (
            automated_task.description in mock_console.print.call_args_list[1].args[0]
        )


# ---------------------------------------------------------------------------
# Convenience Methods
# ---------------------------------------------------------------------------


class TestConvenienceMethods:
    @pytest.fixture(autouse=True)
    def mock_error(self, mocker) -> MagicMock:
        return mocker.patch(f"{_MODULE}.print_error")

    def test_not_found_includes_task_name(self, mocker, mock_error: MagicMock):
        mocker.patch(_PATCH_INFO)

        TaskPresenter.not_found("update-mirrorlist")

        assert "update-mirrorlist" in mock_error.call_args.args[0]

    def test_empty_calls_print_error_and_two_print_info(self, mock_info: MagicMock):

        TaskPresenter.empty()

        assert mock_info.call_count == 2

    def test_invalid_task_type_message(self, mock_error: MagicMock):
        TaskPresenter.invalid_task_type()

        assert "automated" in mock_error.call_args.args[0]
        assert "manual" in mock_error.call_args.args[0]

    def test_error_passes_through_message(self, mock_error: MagicMock):
        TaskPresenter.error("boom")

        mock_error.assert_called_once_with("boom")

    def test_aborted_includes_task_name(self, mocker):
        mock_warning: MagicMock = mocker.patch(_PATCH_WARNING)

        TaskPresenter.aborted("update-mirrorlist")

        assert "update-mirrorlist" in mock_warning.call_args.args[0]


# ---------------------------------------------------------------------------
# _get_status_text
# ---------------------------------------------------------------------------


class TestGetStatusText:
    @pytest.mark.parametrize(
        "status,expected_fragment",
        [
            (TaskStatus.SUCCESS, "SUCCESS"),
            (TaskStatus.FAILURE, "FAILURE"),
            (TaskStatus.PARTIAL, "PARTIAL"),
            (TaskStatus.SKIPPED, "SKIPPED"),
        ],
    )
    def test_maps_each_status_to_expected_text(self, status, expected_fragment):
        text = TaskPresenter._get_status_text(status)

        assert expected_fragment in text


# ---------------------------------------------------------------------------
# _format_task_details
# ---------------------------------------------------------------------------


class TestFormatTaskDetails:
    @pytest.fixture(autouse=True)
    def mock_formatter_factory(self, mocker):
        return mocker.patch(f"{_MODULE}.FormatterFactory")

    def test_includes_status_message_and_duration(self):
        result = _make_result(
            status=TaskStatus.SUCCESS, message="all good", duration_seconds=2.5
        )

        output = TaskPresenter._format_task_details(
            "health-check", result, verbose=False
        )

        assert "SUCCESS" in output
        assert "all good" in output
        assert "2.50s" in output

    def test_includes_error_line_when_error_present(self):
        result = _make_result(error="boom")

        output = TaskPresenter._format_task_details(
            "health-check", result, verbose=False
        )

        assert "Error:" in output
        assert "boom" in output

    def test_omits_error_line_when_error_absent(self):
        result = _make_result(error=None)

        output = TaskPresenter._format_task_details(
            "health-check", result, verbose=False
        )

        assert "Error:" not in output

    def test_omits_details_when_not_verbose(self, mock_formatter_factory):
        result = _make_result(details={"some": "data"})

        output = TaskPresenter._format_task_details(
            "health-check", result, verbose=False
        )

        mock_formatter_factory.get_formatter.assert_not_called()
        assert "Details:" not in output

    def test_omits_details_when_verbose_but_no_details(self, mock_formatter_factory):
        result = _make_result(details={})

        output = TaskPresenter._format_task_details(
            "health-check", result, verbose=True
        )

        mock_formatter_factory.get_formatter.assert_not_called()
        assert "Details:" not in output

    def test_delegates_to_formatter_factory_when_verbose_with_details(
        self, mock_formatter_factory
    ):
        mock_formatter = mock_formatter_factory.get_formatter.return_value
        mock_formatter.format.return_value = ["  cpu: 12%", "  mem: 34%"]
        details = {"cpu_usage_percent": 12}
        result = _make_result(details=details)

        output = TaskPresenter._format_task_details(
            "health-check", result, verbose=True
        )

        mock_formatter_factory.get_formatter.assert_called_once_with("health-check")
        mock_formatter.format.assert_called_once_with(details)
        assert "Details:" in output
        assert "cpu: 12%" in output
        assert "mem: 34%" in output
