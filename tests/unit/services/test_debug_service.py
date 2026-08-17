"""Unit tests for DebugService."""

from unittest.mock import MagicMock

import pytest

from archcare.core.notifications import NotificationManager
from archcare.services import DebugService
from archcare.services.exceptions import (
    InvalidSeverityError,
    NotificationSendError,
    NotificationUnavailableError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def service() -> DebugService:
    mock_manager: MagicMock = MagicMock(spec=NotificationManager)
    return DebugService(mock_manager)


# ---------------------------------------------------------------------------
# Severity validation
# ---------------------------------------------------------------------------


class TestSeverityValidation:
    @pytest.mark.parametrize("severity", ["critical", "warning", "info"])
    def test_valid_severities_are_accepted(self, service: DebugService, severity, mocker):
        mock_manager = service.notification_manager
        mocker.patch.object(mock_manager, "is_available", return_value=True)
        mocker.patch.object(mock_manager, "send_notification", return_value=True)

        result = service.test_notification(severity)
        assert result.severity == severity

    def test_invalid_severity_raises(self, service: DebugService):
        with pytest.raises(InvalidSeverityError) as exc_info:
            service.test_notification("urgent")
        assert exc_info.value.severity == "urgent"
        assert "urgent" in str(exc_info.value)

    def test_invalid_severity_lists_valid_options(self, service: DebugService):
        with pytest.raises(InvalidSeverityError) as exc_info:
            service.test_notification("urgent")
        assert exc_info.value.valid == ["critical", "warning", "info"]


# ---------------------------------------------------------------------------
# Notification availability
# ---------------------------------------------------------------------------


class TestNotificationAvailability:
    def test_raises_when_notify_send_unavailable(self, service: DebugService, mocker):
        mocker.patch.object(service.notification_manager, "is_available", return_value=False)
        with pytest.raises(NotificationUnavailableError):
            service.test_notification("warning")

    def test_proceeds_when_notify_send_available(self, service: DebugService, mocker):
        mock_manager = service.notification_manager
        mocker.patch.object(mock_manager, "is_available", return_value=True)
        mocker.patch.object(mock_manager, "send_notification", return_value=True)

        result = service.test_notification("warning")
        assert result is not None


# ---------------------------------------------------------------------------
# Send failure
# ---------------------------------------------------------------------------


class TestSendNotification:
    def test_raises_on_send_failure(self, service: DebugService, mocker):
        mock_manager = service.notification_manager
        mocker.patch.object(mock_manager, "is_available", return_value=True)
        mocker.patch.object(mock_manager, "send_notification", return_value=False)

        with pytest.raises(NotificationSendError) as exc_info:
            service.test_notification("critical")
        assert exc_info.value.severity == "critical"

    @pytest.mark.parametrize("severity", ["critical", "warning", "info"])
    def test_send_called_with_matching_title(self, service: DebugService, mocker, severity):
        calls = []
        mock_manager = service.notification_manager
        mocker.patch.object(mock_manager, "is_available", return_value=True)
        mocker.patch.object(
            mock_manager,
            "send_notification",
            lambda **kwargs: calls.append(kwargs) or True,
        )

        service.test_notification(severity)
        assert calls[0]["title"] == f"Testing severity `{severity}`"

    def test_response_carries_severity_and_title(self, service: DebugService, mocker):
        mock_manager = service.notification_manager
        mocker.patch.object(mock_manager, "is_available", return_value=True)
        mocker.patch.object(mock_manager, "send_notification", return_value=True)

        result = service.test_notification("warning")
        assert result.severity == "warning"
        assert "warning" in result.title.lower()
