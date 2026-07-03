"""Unit tests for TaskPresenter."""

from typing import Any
from unittest.mock import MagicMock, Mock

import pytest

from archcare.cli.presenters.task_presenter import TaskPresenter
from archcare.config import AppSettings, TaskConfig
from archcare.config.models import MaintenanceCheckSettings
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
