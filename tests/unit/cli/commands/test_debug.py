"""Unit tests for the `debug` command group."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import typer

from archcare.cli.commands.debug import test_notification as notification
from archcare.cli.context import AppContext
from archcare.services.exceptions import (
    InvalidSeverityError,
    NotificationSendError,
    NotificationUnavailableError,
)

_MODULE = "archcare.cli.commands.debug"


# ---------------------------------------------------------------------------
# Fixtures and Helpers
# ---------------------------------------------------------------------------


def _make_ctx(app_context: AppContext | None = None) -> SimpleNamespace:
    return SimpleNamespace(obj=app_context or MagicMock(spec=AppContext))


@pytest.fixture
def mock_presenter(mocker) -> MagicMock:
    return mocker.patch(f"{_MODULE}.DebugPresenter")


@pytest.fixture
def mock_service(mocker) -> MagicMock:
    return mocker.patch(f"{_MODULE}.DebugService").return_value


# ---------------------------------------------------------------------------
# debug - test notification
# ---------------------------------------------------------------------------


class TestTestNotification:
    def test_calls_setup_logging_and_shows_header(
        self, mock_presenter: MagicMock, mock_service: MagicMock
    ):
        mock_service.test_notification.return_value = "RESPONSE_SENTINEL"
        ctx = _make_ctx()

        notification(ctx)  # ty:ignore[invalid-argument-type]

        ctx.obj.setup_logging.assert_called_once()
        mock_presenter.header.assert_called_once()

    @pytest.mark.usefixtures("mock_presenter")
    def test_service_called_with_severity(self, mock_service: MagicMock):
        mock_service.test_notification.return_value = "RESPONSE_SENTINEL"
        ctx = _make_ctx()

        notification(ctx, severity="critical")  # ty:ignore[invalid-argument-type]

        mock_service.test_notification.assert_called_once_with("critical")

    def test_success_renders_response(
        self, mock_presenter: MagicMock, mock_service: MagicMock
    ):
        mock_service.test_notification.return_value = "RESPONSE_SENTINEL"
        ctx = _make_ctx()

        notification(ctx)  # ty:ignore[invalid-argument-type]

        mock_presenter.render_test_notification.assert_called_once_with("RESPONSE_SENTINEL")

    def test_invalid_severity_shows_message_and_exits_1(
        self, mock_presenter: MagicMock, mock_service: MagicMock
    ):
        exc = InvalidSeverityError("urgent", ["critical", "warning", "info"])
        mock_service.test_notification.side_effect = exc
        ctx = _make_ctx()

        with pytest.raises(typer.Exit) as exc_info:
            notification(ctx, severity="urgent")  # ty:ignore[invalid-argument-type]

        mock_presenter.invalid_severity.assert_called_once_with(exc)
        assert exc_info.value.exit_code == 1

    def test_notification_unavailable_shows_message_and_exits_1(
        self, mock_presenter: MagicMock, mock_service: MagicMock
    ):
        mock_service.test_notification.side_effect = NotificationUnavailableError()
        ctx = _make_ctx()

        with pytest.raises(typer.Exit) as exc_info:
            notification(ctx)  # ty:ignore[invalid-argument-type]

        mock_presenter.notification_unavailable.assert_called_once()
        assert exc_info.value.exit_code == 1

    def test_notification_send_error_shows_message_and_exits_1(
        self, mock_presenter: MagicMock, mock_service: MagicMock
    ):
        mock_service.test_notification.side_effect = NotificationSendError("critical")
        ctx = _make_ctx()

        with pytest.raises(typer.Exit) as exc_info:
            notification(ctx, severity="critical")  # ty:ignore[invalid-argument-type]

        mock_presenter.notification_send_failed.assert_called_once()
        assert exc_info.value.exit_code == 1

    def test_generic_exception_shows_message_and_exits_1(
        self, mocker, mock_service: MagicMock
    ):
        mock_error: MagicMock = mocker.patch(f"{_MODULE}.print_error")
        mock_service.test_notification.side_effect = Exception("test")
        ctx = _make_ctx()

        with pytest.raises(typer.Exit) as exc_info:
            notification(ctx)  # ty:ignore[invalid-argument-type]

        mock_error.assert_called_once()
        assert exc_info.value.exit_code == 1
