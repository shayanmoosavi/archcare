"""Typer commands for debugging purposes."""

from typing import Any

import typer

from archcare.config import AppSettings
from archcare.cli import _state
from archcare.utils import setup_logging
from archcare.utils.notifications import (
    send_notification,
    is_notification_available,
    NotificationUrgency,
    NotificationIcon,
)
from archcare.utils.output import print_header, print_info, print_success, print_error

debug_app = typer.Typer(help="Debug commands for Archcare.")


@debug_app.command()
def test_notification(
    severity: str = typer.Option(
        "warning",
        "--severity",
        "-s",
        help="Notification severity: critical, warning, or info",
    ),
):
    """
    Test desktop notifications.

    Sends a test notification to verify the notification system is working.

    Example:
        archcare debug test-notification
        archcare debug test-notification --severity critical
    """

    # Validate severity
    valid_severities = ["critical", "warning", "info"]
    severity_config: dict[str, Any] = {}
    match severity:
        case "critical":
            severity_config = {
                "urgency": NotificationUrgency.CRITICAL,
                "icon": NotificationIcon.ERROR,
                "title": "Testing severity `critical`",
            }
        case "warning":
            severity_config = {
                "urgency": NotificationUrgency.NORMAL,
                "icon": NotificationIcon.WARNING,
                "title": "Testing severity `warning`",
            }
        case "info":
            severity_config = {
                "urgency": NotificationUrgency.LOW,
                "icon": NotificationIcon.INFO,
                "title": "Testing severity `info`",
            }
        case _:
            print_error(f"Invalid severity: {severity}")
            print_info(f"Valid options: {', '.join(valid_severities)}")
            raise typer.Exit(1)

    # Setup default logging
    default_settings = AppSettings()
    default_settings.ensure_directories()
    setup_logging(default_settings, devel_mode=_state._devel)

    print_header("Testing Desktop Notifications")

    # Check if notifications are available
    if not is_notification_available():
        print_error("Desktop notifications are not available on this system")
        print_info("Install libnotify package to enable notifications:")
        print_info("  sudo pacman -S libnotify")
        raise typer.Exit(1)

    print_success("notify-send is available")

    # Send test notification
    print_info(f"Sending test notification with severity: {severity}")

    success = send_notification(
        title=severity_config["title"],
        message="This is a test notification from archcare.\nNotifications are working correctly!",
        urgency=severity_config["urgency"],
        icon=severity_config["icon"],
    )

    if success:
        print_success("Test notification sent successfully!")
        print_info("Check your notification area to see if it appeared")
    else:
        print_error("Failed to send notification")
        print_info("Check the logs for more details:")
        print_info("  archcare logs")
        raise typer.Exit(1)
