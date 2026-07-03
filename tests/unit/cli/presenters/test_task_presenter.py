"""Unit tests for TaskPresenter."""

from typing import Any
from unittest.mock import MagicMock, Mock

import pytest

from archcare.cli.presenters.task_presenter import TaskPresenter
from archcare.config import AppSettings, TaskConfig
from archcare.config.models import MaintenanceCheckSettings
from archcare.core import TaskScheduleInfo
from archcare.core.models import TaskResult
from archcare.services.responses import (
    TaskListResponse,
    TaskRunResponse,
    TaskStatusResponse,
)

_MODULE = "archcare.cli.presenters.task_presenter"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_outcome(
    is_skipped: bool = False, details: dict[str, Any] | None = None
) -> Mock:
    """A minimal TaskResult stand-in exposing only what TaskPresenter reads."""
    outcome = Mock(spec=TaskResult)
    outcome.is_skipped.return_value = is_skipped
    outcome.details = details or {}
    return outcome


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


# ---------------------------------------------------------------------------
# render_run
# ---------------------------------------------------------------------------


class TestRenderRun:
    def test_header_shown_when_outcome_not_skipped(
        self, settings_terminal_mode: AppSettings, mocker
    ):
        mock_header: MagicMock = mocker.patch(f"{_MODULE}.print_header")
        mocker.patch(f"{_MODULE}.print_task_result")

        response = TaskRunResponse(
            task_name="update-mirrorlist",
            outcome=_make_outcome(is_skipped=False),
            is_interactive=True,
        )
        TaskPresenter.render_run(response, settings_terminal_mode)

        mock_header.assert_called_once_with(f"Running Task: {response.task_name}", True)

    def test_header_skipped_when_outcome_is_skipped(
        self, settings_terminal_mode: AppSettings, mocker
    ):
        mock_header: MagicMock = mocker.patch(f"{_MODULE}.print_header")
        mocker.patch(f"{_MODULE}.print_task_result")

        response = TaskRunResponse(
            task_name="update-mirrorlist",
            outcome=_make_outcome(is_skipped=True),
            is_interactive=True,
        )
        TaskPresenter.render_run(response, settings_terminal_mode)

        mock_header.assert_not_called()

    def test_renders_maintenance_table_when_result_present_and_not_file_mode(
        self, settings_terminal_mode: AppSettings, mocker
    ):
        mocker.patch(f"{_MODULE}.print_header")
        mocker.patch(f"{_MODULE}.print_task_result")
        mocker.patch(f"{_MODULE}.print_info")
        mock_mc_presenter: MagicMock = mocker.patch(
            f"{_MODULE}.MaintenanceCheckPresenter"
        )

        sentinel_result = object()
        response = TaskRunResponse(
            task_name="check-maintenance",
            outcome=_make_outcome(details={"maintenance_result": sentinel_result}),
            is_interactive=True,
        )
        TaskPresenter.render_run(response, settings_terminal_mode)

        mock_mc_presenter.render.assert_called_once_with(
            sentinel_result, is_interactive=True, require_acknowledgment=True
        )

    def test_shows_file_mode_message_instead_of_table(
        self, settings_file_mode: AppSettings, mocker
    ):
        """
        output_mode='file' must skip the table entirely and print a
        pointer to the report file instead - the message dynamically
        reflects settings.report_dir rather than a hardcoded path, so
        this stays portable across machines/CI.
        """
        mocker.patch(f"{_MODULE}.print_header")
        mocker.patch(f"{_MODULE}.print_task_result")
        mock_info: MagicMock = mocker.patch(f"{_MODULE}.print_info")
        mock_mc_presenter: MagicMock = mocker.patch(
            f"{_MODULE}.MaintenanceCheckPresenter"
        )

        response = TaskRunResponse(
            task_name="check-maintenance",
            outcome=_make_outcome(details={"maintenance_result": object()}),
            is_interactive=True,
        )
        TaskPresenter.render_run(response, settings_file_mode)

        mock_mc_presenter.render.assert_not_called()
        mock_info.assert_called_once()
        assert str(settings_file_mode.report_dir) in mock_info.call_args.args[0]

    def test_no_maintenance_rendering_when_maintenance_result_absent(
        self, settings_terminal_mode: AppSettings, mocker
    ):
        mocker.patch(f"{_MODULE}.print_header")
        mocker.patch(f"{_MODULE}.print_task_result")
        mock_info: MagicMock = mocker.patch(f"{_MODULE}.print_info")
        mock_mc_presenter: MagicMock = mocker.patch(
            f"{_MODULE}.MaintenanceCheckPresenter"
        )

        response = TaskRunResponse(
            task_name="failed-services",
            outcome=_make_outcome(details={}),
            is_interactive=True,
        )
        TaskPresenter.render_run(response, settings_terminal_mode)

        mock_mc_presenter.render.assert_not_called()
        mock_info.assert_not_called()

    def test_verbose_uses_print_task_details_with_show_details(
        self, settings_terminal_mode: AppSettings, mocker
    ):
        mocker.patch(f"{_MODULE}.print_header")
        mock_details: MagicMock = mocker.patch(f"{_MODULE}.print_task_details")
        mock_result: MagicMock = mocker.patch(f"{_MODULE}.print_task_result")

        outcome = _make_outcome(details={})
        response = TaskRunResponse(
            task_name="check-health", outcome=outcome, is_interactive=True
        )
        TaskPresenter.render_run(response, settings_terminal_mode, verbose=True)

        mock_details.assert_called_once_with(
            "check-health", outcome, show_details=True, is_interactive=True
        )
        mock_result.assert_not_called()

    def test_non_verbose_uses_print_task_result(
        self, settings_terminal_mode: AppSettings, mocker
    ):
        mocker.patch(f"{_MODULE}.print_header")
        mock_details: MagicMock = mocker.patch(f"{_MODULE}.print_task_details")
        mock_result: MagicMock = mocker.patch(f"{_MODULE}.print_task_result")

        outcome = _make_outcome(details={})
        response = TaskRunResponse(
            task_name="check-health", outcome=outcome, is_interactive=True
        )
        TaskPresenter.render_run(response, settings_terminal_mode, verbose=False)

        mock_result.assert_called_once_with(outcome, "check-health", True)
        mock_details.assert_not_called()


# ---------------------------------------------------------------------------
# render_status
# ---------------------------------------------------------------------------


class TestRenderStatus:
    def test_due_only_with_no_schedule_shows_success_and_returns_early(self, mocker):
        mock_success: MagicMock = mocker.patch(f"{_MODULE}.print_success")
        mock_table: MagicMock = mocker.patch(f"{_MODULE}.print_schedule_table")

        response = TaskStatusResponse(schedule_info=[], due_only=True)
        TaskPresenter.render_status(response)

        mock_success.assert_called_once_with("No tasks currently due!")
        mock_table.assert_not_called()

    def test_due_only_with_results_shows_table_not_success(self, mocker):
        mock_success: MagicMock = mocker.patch(f"{_MODULE}.print_success")
        mock_table: MagicMock = mocker.patch(f"{_MODULE}.print_schedule_table")

        mock_task_info = MagicMock(spec=TaskScheduleInfo)
        response = TaskStatusResponse(schedule_info=[mock_task_info], due_only=True)
        TaskPresenter.render_status(response)

        mock_table.assert_called_once_with([mock_task_info])
        mock_success.assert_not_called()

    def test_non_due_only_with_empty_schedule_still_shows_table(self, mocker):
        mock_success: MagicMock = mocker.patch(f"{_MODULE}.print_success")
        mock_table: MagicMock = mocker.patch(f"{_MODULE}.print_schedule_table")

        response = TaskStatusResponse(schedule_info=[], due_only=False)
        TaskPresenter.render_status(response)

        mock_table.assert_called_once_with([])
        mock_success.assert_not_called()

    def test_summary_panel_rendered_when_summary_present(self, mocker):
        mocker.patch(f"{_MODULE}.print_schedule_table")
        mock_panel: MagicMock = mocker.patch(f"{_MODULE}.print_summary_panel")

        summary = {"total": 3, "overdue": 1}
        response = TaskStatusResponse(
            schedule_info=[MagicMock(spec=TaskScheduleInfo)], summary=summary
        )
        TaskPresenter.render_status(response)

        mock_panel.assert_called_once_with("Summary", summary)

    def test_summary_panel_not_rendered_when_no_summary(self, mocker):
        mocker.patch(f"{_MODULE}.print_schedule_table")
        mock_panel: MagicMock = mocker.patch(f"{_MODULE}.print_summary_panel")

        response = TaskStatusResponse(
            schedule_info=[MagicMock(spec=TaskScheduleInfo)], summary=None
        )
        TaskPresenter.render_status(response)

        mock_panel.assert_not_called()


# ---------------------------------------------------------------------------
# render_list
# ---------------------------------------------------------------------------


class TestRenderList:
    def test_shows_header_regardless_of_content(self, mocker):
        mock_header: MagicMock = mocker.patch(f"{_MODULE}.print_header")
        mocker.patch(f"{_MODULE}.print_warning")

        TaskPresenter.render_list(TaskListResponse(tasks={}, filtered_by=None))

        mock_header.assert_called_once_with("Available Tasks")

    def test_empty_tasks_shows_warning_and_returns(self, mocker):
        mocker.patch(f"{_MODULE}.print_header")
        mock_warning: MagicMock = mocker.patch(f"{_MODULE}.print_warning")
        mock_console: MagicMock = mocker.patch(f"{_MODULE}.console")

        TaskPresenter.render_list(TaskListResponse(tasks={}, filtered_by=None))

        mock_warning.assert_called_once_with("No tasks found!")
        mock_console.print.assert_not_called()

    def test_enabled_task_uses_checkmark_icon(self, automated_task: TaskConfig, mocker):
        mocker.patch(f"{_MODULE}.print_header")
        mock_console: MagicMock = mocker.patch(f"{_MODULE}.console")

        response = TaskListResponse(
            tasks={automated_task.name: automated_task}, filtered_by=None
        )
        TaskPresenter.render_list(response)

        first_line: MagicMock = mock_console.print.call_args_list[0][0][0]
        assert "✓" in first_line
        assert automated_task.name in first_line

    def test_disabled_task_uses_cross_icon(self, disabled_task: TaskConfig, mocker):
        mocker.patch(f"{_MODULE}.print_header")
        mock_console: MagicMock = mocker.patch(f"{_MODULE}.console")

        response = TaskListResponse(
            tasks={disabled_task.name: disabled_task}, filtered_by=None
        )
        TaskPresenter.render_list(response)

        first_line: MagicMock = mock_console.print.call_args_list[0][0][0]
        assert "✗" in first_line

    def test_console_print_called_twice_per_task(
        self, automated_task: TaskConfig, mocker
    ):
        """
        Pins down the name-line + description-line structure, so a future
        refactor collapsing them into one print() silently drops the
        description without any test noticing.
        """
        mocker.patch(f"{_MODULE}.print_header")
        mock_console: MagicMock = mocker.patch(f"{_MODULE}.console")

        response = TaskListResponse(
            tasks={automated_task.name: automated_task}, filtered_by=None
        )
        TaskPresenter.render_list(response)

        assert mock_console.print.call_count == 2
        assert automated_task.description in mock_console.print.call_args_list[1][0][0]
