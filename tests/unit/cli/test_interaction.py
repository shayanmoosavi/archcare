"""Unit tests for CliInteraction."""

from unittest.mock import MagicMock

import pytest

from archcare.cli.interaction import CliInteraction

_MODULE = "archcare.cli.interaction"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_warning(mocker) -> MagicMock:
    return mocker.patch(f"{_MODULE}.print_warning")


@pytest.fixture
def mock_info(mocker) -> MagicMock:
    return mocker.patch(f"{_MODULE}.print_info")


class TestCliInteraction:
    # --- notify ------------------------------------------------------------
    def test_notify_warning_level_routes_to_print_warning(
        self, mock_warning: MagicMock, mock_info: MagicMock
    ):
        interaction = CliInteraction()
        interaction.notify("disk almost full", level="warning")

        mock_warning.assert_called_once_with("disk almost full")
        mock_info.assert_not_called()

    def test_notify_default_level_routes_to_print_info(
        self, mock_warning: MagicMock, mock_info: MagicMock
    ):
        interaction = CliInteraction()
        interaction.notify("task started")

        mock_info.assert_called_once_with("task started")
        mock_warning.assert_not_called()

    # --- confirm -----------------------------------------------------------
    def test_confirm_delegates_to_typer_confirm(self, mocker):
        mock_confirm: MagicMock = mocker.patch(f"{_MODULE}.typer.confirm", return_value=True)

        result = CliInteraction.confirm("Run anyway?")

        mock_confirm.assert_called_once_with("Run anyway?")
        assert result is True
