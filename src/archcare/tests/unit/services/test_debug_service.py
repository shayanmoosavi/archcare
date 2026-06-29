"""Unit tests for DebugService."""

import pytest

from archcare.services import DebugService
from archcare.services.exceptions import (
    InvalidSeverityError,
    NotificationSendError,
    NotificationUnavailableError,
)

_PATCH_AVAILABLE = "archcare.services.debug_service.is_notification_available"
_PATCH_SEND = "archcare.services.debug_service.send_notification"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def service() -> DebugService:
    return DebugService()


# ---------------------------------------------------------------------------
# Severity validation
# ---------------------------------------------------------------------------


class TestSeverityValidation:
    @pytest.mark.parametrize("severity", ["critical", "warning", "info"])
    def test_valid_severities_are_accepted(
        self, service: DebugService, severity, monkeypatch
    ):
        monkeypatch.setattr(_PATCH_AVAILABLE, lambda: True)
        monkeypatch.setattr(_PATCH_SEND, lambda **_: True)
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
    def test_raises_when_notify_send_unavailable(
        self, service: DebugService, monkeypatch
    ):
        monkeypatch.setattr(_PATCH_AVAILABLE, lambda: False)
        with pytest.raises(NotificationUnavailableError):
            service.test_notification("warning")

    def test_proceeds_when_notify_send_available(
        self, service: DebugService, monkeypatch
    ):
        monkeypatch.setattr(_PATCH_AVAILABLE, lambda: True)
        monkeypatch.setattr(_PATCH_SEND, lambda **_: True)
        result = service.test_notification("warning")
        assert result is not None


# ---------------------------------------------------------------------------
# Send failure
# ---------------------------------------------------------------------------


class TestSendNotification:
    def test_raises_on_send_failure(self, service: DebugService, monkeypatch):
        monkeypatch.setattr(_PATCH_AVAILABLE, lambda: True)
        monkeypatch.setattr(_PATCH_SEND, lambda **_: False)
        with pytest.raises(NotificationSendError) as exc_info:
            service.test_notification("critical")
        assert exc_info.value.severity == "critical"

    @pytest.mark.parametrize("severity", ["critical", "warning", "info"])
    def test_send_called_with_matching_title(
        self, service: DebugService, monkeypatch, severity
    ):
        calls = []
        monkeypatch.setattr(_PATCH_AVAILABLE, lambda: True)
        monkeypatch.setattr(_PATCH_SEND, lambda **kwargs: calls.append(kwargs) or True)
        service.test_notification(severity)
        assert calls[0]["title"] == f"Testing severity `{severity}`"

    def test_response_carries_severity_and_title(
        self, service: DebugService, monkeypatch
    ):
        monkeypatch.setattr(_PATCH_AVAILABLE, lambda: True)
        monkeypatch.setattr(_PATCH_SEND, lambda **_: True)
        result = service.test_notification("warning")
        assert result.severity == "warning"
        assert "warning" in result.title.lower()
