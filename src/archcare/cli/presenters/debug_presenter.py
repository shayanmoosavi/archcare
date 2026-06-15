"""Presenter for the `debug` command group."""

from archcare.services.exceptions import InvalidSeverityError
from archcare.services.responses import NotificationTestResponse
from archcare.utils.output import print_error, print_header, print_info, print_success


class DebugPresenter:
    """Renders DebugService results and errors to the terminal."""

    @staticmethod
    def header() -> None:
        print_header("Testing Desktop Notifications")

    @staticmethod
    def render_test_notification(response: NotificationTestResponse) -> None:
        print_success("notify-send is available")
        print_info(f"Sending test notification with severity: {response.severity}")
        print_success("Test notification sent successfully!")
        print_info("Check your notification area to see if it appeared")

    @staticmethod
    def invalid_severity(exc: InvalidSeverityError) -> None:
        print_error(f"Invalid severity: {exc.severity}")
        print_info(f"Valid options: {', '.join(exc.valid)}")

    @staticmethod
    def notification_unavailable() -> None:
        print_error("Desktop notifications are not available on this system")
        print_info("Install libnotify package to enable notifications:")
        print_info("  sudo pacman -S libnotify")

    @staticmethod
    def notification_send_failed() -> None:
        print_error("Failed to send notification")
        print_info("Check the logs for more details:")
        print_info("  archcare logs")
