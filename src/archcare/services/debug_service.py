"""Debug service - business logic for the `debug` command group."""

from typing import Any

from archcare.core.notifications import (
    NotificationIcon,
    NotificationManager,
    NotificationUrgency,
)

from .exceptions import (
    InvalidSeverityError,
    NotificationSendError,
    NotificationUnavailableError,
)
from .responses import NotificationTestResponse

_SEVERITY_CONFIG: dict[str, dict[str, Any]] = {
    "critical": {
        "urgency": NotificationUrgency.CRITICAL,
        "icon": NotificationIcon.ERROR,
        "title": "Testing severity `critical`",
    },
    "warning": {
        "urgency": NotificationUrgency.NORMAL,
        "icon": NotificationIcon.WARNING,
        "title": "Testing severity `warning`",
    },
    "info": {
        "urgency": NotificationUrgency.LOW,
        "icon": NotificationIcon.INFO,
        "title": "Testing severity `info`",
    },
}


class DebugService:
    """Business logic for the `debug` command group."""

    def __init__(self, notification_manager: NotificationManager):
        self.notification_manager = notification_manager

    def test_notification(self, severity: str = "warning") -> NotificationTestResponse:
        """
        Send a test desktop notification.

        Raises:
            InvalidSeverityError: If `severity` isn't critical/warning/info.
            NotificationUnavailableError: If notify-send/libnotify isn't available.
            NotificationSendError: If sending the notification fails.
        """
        config = _SEVERITY_CONFIG.get(severity)
        if config is None:
            raise InvalidSeverityError(severity, valid=list(_SEVERITY_CONFIG))

        if not self.notification_manager.is_available():
            raise NotificationUnavailableError()

        sent = self.notification_manager.send_notification(
            title=config["title"],
            message=(
                "This is a test notification from archcare.\n"
                "Notifications are working correctly!"
            ),
            urgency=config["urgency"],
            icon=config["icon"],
        )

        if not sent:
            raise NotificationSendError(severity)

        return NotificationTestResponse(severity=severity, title=config["title"])
