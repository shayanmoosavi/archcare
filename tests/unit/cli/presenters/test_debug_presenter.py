"""Unit tests for DebugPresenter."""

from unittest.mock import MagicMock

import pytest

from archcare.cli.presenters import DebugPresenter
from archcare.services.exceptions import InvalidSeverityError
from archcare.services.responses import NotificationTestResponse

_MODULE = "archcare.cli.presenters.debug_presenter"
_PATCH_ERROR = f"{_MODULE}.print_error"


@pytest.fixture
def mock_info(mocker) -> MagicMock:
    return mocker.patch(f"{_MODULE}.print_info")


class TestDebugPresenter:
    def test_header_shows_header(self, mocker):
        mock_header: MagicMock = mocker.patch(f"{_MODULE}.print_header")

        DebugPresenter.header()

        mock_header.assert_called_once_with("Testing Desktop Notifications")

    def test_render_test_notification_includes_severity(self, mocker, mock_info: MagicMock):
        mocker.patch(f"{_MODULE}.print_success")

        response = NotificationTestResponse(
            severity="critical", title="Testing severity `critical`"
        )
        DebugPresenter.render_test_notification(response)

        assert "critical" in mock_info.call_args_list[0].args[0]

    def test_invalid_severity_includes_severity_and_valid_options(
        self, mocker, mock_info: MagicMock
    ):
        mock_error: MagicMock = mocker.patch(_PATCH_ERROR)

        exc = InvalidSeverityError("urgent", ["critical", "warning", "info"])
        DebugPresenter.invalid_severity(exc)

        assert "urgent" in mock_error.call_args.args[0]
        assert "critical, warning, info" in mock_info.call_args.args[0]

    def test_notification_unavailable_mentions_libnotify_install(
        self, mocker, mock_info: MagicMock
    ):
        mocker.patch(_PATCH_ERROR)

        DebugPresenter.notification_unavailable()

        joined = " ".join(c.args[0] for c in mock_info.call_args_list)
        assert "libnotify" in joined

    def test_notification_send_failure_points_to_logs(self, mocker, mock_info: MagicMock):
        mocker.patch(_PATCH_ERROR)

        DebugPresenter.notification_send_failed()

        joined = " ".join(c.args[0] for c in mock_info.call_args_list)
        assert "archcare logs" in joined
