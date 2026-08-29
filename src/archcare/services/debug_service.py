"""
Debug service - business logic for the `debug` command group.

Currently provides a single capability: sending a test desktop notification
([DebugService.test_notification][]) so users can verify that `notify-send`/libnotify works before
archcare relies on it during task runs ([NotificationManager][]).

Severity presets (`critical`, `warning`, `info`) are defined in the module-level `_SEVERITY_CONFIG`
mapping, which pairs each severity with a notification urgency, icon, and title template.

All methods return response DTOs from [archcare.services.responses][] so the CLI layer never
handles raw business state.

See Also:
    - [archcare.services.exceptions][]: Service-layer error hierarchy used here
    - [archcare.cli.commands.debug][]: CLI commands delegating to this service
"""

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
    # Maps each accepted severity name to the notification parameters used
    # for the test notification: urgency, icon, and title template.
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
    """
    Business logic for the `debug` command group.

    Wraps the notification subsystem for diagnostics: validates the requested severity, checks that
    desktop notifications are available on this system, and sends a sample notification — surfacing
    each failure mode as a distinct, user-actionable exception.

    Attributes:
        notification_manager (NotificationManager): Manager used to probe availability and dispatch
            the test notification.
    """

    def __init__(self, notification_manager: NotificationManager):
        """
        Initialize the debug service.

        Args:
            notification_manager (NotificationManager): Lazily constructed manager wrapping
                `notify-send` availability checks and notification dispatch.
        """
        self.notification_manager = notification_manager

    def test_notification(self, severity: str = "warning") -> NotificationTestResponse:
        """
        Send a test desktop notification.

        Looks up the severity preset in `_SEVERITY_CONFIG` (which maps each severity to its urgency,
        icon, and title), verifies that the notification backend is available, and dispatches the
        notification. Each failure stage raises a distinct exception so the CLI can suggest the
        right fix (valid severity, install libnotify, check sending environment, respectively).

        Args:
            severity (str): Severity preset for the test notification — one of `"critical"`,
                `"warning"`, or `"info"`. Defaults to `"warning"`.

        Returns:
            NotificationTestResponse: The severity used and the notification's title (on success).

        Raises:
            InvalidSeverityError: If `severity` isn't one of critical/warning/info.
            NotificationUnavailableError: If notify-send/libnotify isn't available.
            NotificationSendError: If sending the notification fails
                (the backend reported non-success).

        Side Effects:
            Displays a desktop notification on the user's session via `notify-send`.

        Examples:
            ```python
            response = DebugService(NotificationManager()).test_notification()
            # -> NotificationTestResponse(
            #        severity="warning", title="Testing severity `warning`"
            #    )
            ```
        """
        config = _SEVERITY_CONFIG.get(severity)
        if config is None:
            raise InvalidSeverityError(severity, valid=list(_SEVERITY_CONFIG))

        if not self.notification_manager.is_available():
            raise NotificationUnavailableError()

        sent = self.notification_manager.send_notification(
            title=config["title"],
            message=(
                "This is a test notification from archcare.\nNotifications are working correctly!"
            ),
            urgency=config["urgency"],
            icon=config["icon"],
        )

        if not sent:
            raise NotificationSendError(severity)

        return NotificationTestResponse(severity=severity, title=config["title"])
