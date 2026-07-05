"""Unit tests for the `setup` command group."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import typer

from archcare.cli.commands.setup import setup_config, setup_timers
from archcare.services.exceptions import (
    NotRootError,
    SystemdReloadError,
    UserDetectionError,
)

_MODULE = "archcare.cli.commands.setup"


# ---------------------------------------------------------------------------
# Fixtures and Helpers
# ---------------------------------------------------------------------------


def _make_ctx(app_context=None) -> SimpleNamespace:
    return SimpleNamespace(obj=app_context or MagicMock())


@pytest.fixture
def mock_presenter(mocker) -> MagicMock:
    return mocker.patch(f"{_MODULE}.SetupPresenter")


@pytest.fixture
def mock_service(mocker) -> MagicMock:
    return mocker.patch(f"{_MODULE}.ConfigService").return_value


# ---------------------------------------------------------------------------
# setup config
# ---------------------------------------------------------------------------


class TestSetupConfig:
    def test_no_existing_files_initializes_without_prompting(
        self, mocker, mock_presenter: MagicMock, mock_service: MagicMock
    ):
        mock_confirm: MagicMock = mocker.patch(f"{_MODULE}.typer.confirm")
        mock_service.check_existing.return_value = []
        mock_service.initialize.return_value = "RESULT_SENTINEL"

        setup_config()

        mock_confirm.assert_not_called()
        mock_service.initialize.assert_called_once()
        mock_presenter.render_config_init.assert_called_once_with("RESULT_SENTINEL")

    def test_config_header_uses_service_config_dir(
        self, tmp_path, mock_presenter: MagicMock, mock_service: MagicMock
    ):
        mock_service.check_existing.return_value = []
        mock_service.config_dir = tmp_path

        setup_config()

        mock_presenter.config_header.assert_called_once_with(tmp_path)

    def test_existing_files_confirmed_still_initializes(
        self, mocker, mock_presenter: MagicMock, mock_service: MagicMock
    ):
        mocker.patch(f"{_MODULE}.typer.confirm", return_value=True)
        mock_service.check_existing.return_value = ["settings.toml"]

        setup_config()

        mock_presenter.existing_files_warning.assert_called_once_with(["settings.toml"])
        mock_service.initialize.assert_called_once()
        mock_presenter.init_cancelled.assert_not_called()

    def test_existing_files_declined_cancels_without_initializing(
        self, mocker, mock_presenter: MagicMock, mock_service: MagicMock
    ):
        mocker.patch(f"{_MODULE}.typer.confirm", return_value=False)
        mock_service.check_existing.return_value = ["settings.toml"]

        with pytest.raises(typer.Exit) as exc_info:
            setup_config()

        mock_presenter.init_cancelled.assert_called_once()
        mock_service.initialize.assert_not_called()
        assert exc_info.value.exit_code == 0
