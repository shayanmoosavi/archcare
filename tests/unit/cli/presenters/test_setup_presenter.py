"""Unit tests for SetupPresenter."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from archcare.cli.presenters.setup_presenter import SetupPresenter, _list_timers
from archcare.config import TaskConfig
from archcare.services.responses import (
    ConfigInitResponse,
    InstallTemplatesResponse,
    ReloadSystemdResponse,
    TimerEnableResponse,
    TimerSetupResponse,
)

_MODULE = "archcare.cli.presenters.setup_presenter"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _timer_setup_response(**overrides) -> TimerSetupResponse:
    defaults: dict[str, Any] = {
        "automated_tasks": {},
        "enabled_timers": [],
        "timer_status": None,
    }
    return TimerSetupResponse(**{**defaults, **overrides})


def _was_called_with(mock, *args, **kwargs) -> bool:
    """Check call_args_list for an exact (args, kwargs) match, since some
    tests need to assert a *specific* call is absent among many other
    unrelated print/print_info calls the same method makes."""
    return any(c.args == args and c.kwargs == kwargs for c in mock.call_args_list)


# ---------------------------------------------------------------------------
# setup config
# ---------------------------------------------------------------------------


class TestExistingFilesWarning:
    def test_prints_warning_header(self, mocker):
        mock_warning: MagicMock = mocker.patch(f"{_MODULE}.print_warning")
        mocker.patch(f"{_MODULE}.print")

        SetupPresenter.existing_files_warning([])

        mock_warning.assert_called_once_with("Configuration files already exist:")

    def test_prints_each_file_name(self, tmp_path, mocker):
        mocker.patch(f"{_MODULE}.print_warning")
        mock_print: MagicMock = mocker.patch(f"{_MODULE}.print")

        files = [tmp_path / "settings.toml", tmp_path / "tasks.toml"]
        SetupPresenter.existing_files_warning(files)

        assert mock_print.call_count == 2
        assert "settings.toml" in mock_print.call_args_list[0].args[0]
        assert "tasks.toml" in mock_print.call_args_list[1].args[0]

    def test_no_file_lines_when_list_empty(self, mocker):
        mocker.patch(f"{_MODULE}.print_warning")
        mock_print: MagicMock = mocker.patch(f"{_MODULE}.print")

        SetupPresenter.existing_files_warning([])

        mock_print.assert_not_called()


# ---------------------------------------------------------------------------
# Static / no-logic methods - smoke tests only
# ---------------------------------------------------------------------------


class TestStaticMethods:
    def test_config_header(self, tmp_path, mocker):
        mocker.patch(f"{_MODULE}.print_header")
        mock_info: MagicMock = mocker.patch(f"{_MODULE}.print_info")

        SetupPresenter.config_header(tmp_path)

        assert str(tmp_path) in mock_info.call_args.args[0]

    def test_init_cancelled(self, mocker):
        mock_info: MagicMock = mocker.patch(f"{_MODULE}.print_info")

        SetupPresenter.init_cancelled()

        mock_info.assert_called_once_with("Initialization cancelled")

    def test_render_config_init(self, mocker, tmp_path):
        mocker.patch(f"{_MODULE}.print_success")
        mock_info: MagicMock = mocker.patch(f"{_MODULE}.print_info")

        SetupPresenter.render_config_init(ConfigInitResponse(config_dir=tmp_path))

        assert str(tmp_path) in mock_info.call_args_list[0].args[0]
