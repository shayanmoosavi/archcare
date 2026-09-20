"""
Presenter for the `debug` command group.

Owns all terminal rendering for [`DebugService`][archcare.services.debug_service.DebugService]
results and errors: the test-notification flow (availability check, dispatch, follow-up hint) and
the per-failure-mode error messages (invalid severity, missing libnotify, send failure). All methods
are static — the presenter is stateless.

See Also:
    - [`archcare.services.debug_service`][]: Producer of the responses and errors rendered here
"""

from archcare.services.exceptions import InvalidSeverityError
from archcare.services.responses import NotificationTestResponse
from archcare.utils import print_error, print_header, print_info, print_success


class DebugPresenter:
    """
    Renders [`DebugService`][archcare.services.debug_service.DebugService] results and errors
    to the terminal.
    """

    @staticmethod
    def header() -> None:
        """Print the header for the notification test flow."""
        print_header("Testing Desktop Notifications")

    @staticmethod
    def render_test_notification(response: NotificationTestResponse) -> None:
        """
        Render the success path of the notification test.

        Confirms notify-send availability, echoes the severity used, and
        directs the user to verify the notification visually.

        Args:
            response (NotificationTestResponse): Test outcome from
                [`DebugService.test_notification`][archcare.services.debug_service.DebugService.test_notification].
        """
        print_success("notify-send is available")
        print_info(f"Sending test notification with severity: {response.severity}")
        print_success("Test notification sent successfully!")
        print_info("Check your notification area to see if it appeared")

    @staticmethod
    def invalid_severity(exc: InvalidSeverityError) -> None:
        """
        Render the error for an unrecognized severity value.

        Args:
            exc (InvalidSeverityError): The raised exception, carrying the invalid value and the
                list of valid options.
        """
        print_error(f"Invalid severity: {exc.severity}")
        print_info(f"Valid options: {', '.join(exc.valid)}")

    @staticmethod
    def notification_unavailable() -> None:
        """
        Render the error shown when notify-send/libnotify is missing.

        Includes the pacman install hint for Arch Linux.
        """
        print_error("Desktop notifications are not available on this system")
        print_info("Install libnotify package to enable notifications:")
        print_info("  sudo pacman -S libnotify")

    @staticmethod
    def notification_send_failed() -> None:
        """
        Render the error shown when dispatching the notification failed.

        Directs the user to the archcare logs for details.
        """
        print_error("Failed to send notification")
        print_info("Check the logs for more details:")
        print_info("  archcare logs")
