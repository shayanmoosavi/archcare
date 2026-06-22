"""Typer commands for debugging purposes."""

import typer

from archcare.cli.presenters import DebugPresenter
from archcare.services import DebugService
from archcare.services.exceptions import (
    InvalidSeverityError,
    NotificationSendError,
    NotificationUnavailableError,
)

debug_app = typer.Typer(help="Debug commands for Archcare.")


@debug_app.command()
def test_notification(
    ctx: typer.Context,
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
    ctx.obj.setup_logging()
    DebugPresenter.header()

    try:
        response = DebugService().test_notification(severity)
    except InvalidSeverityError as e:
        DebugPresenter.invalid_severity(e)
        raise typer.Exit(1)
    except NotificationUnavailableError:
        DebugPresenter.notification_unavailable()
        raise typer.Exit(1)
    except NotificationSendError:
        DebugPresenter.notification_send_failed()
        raise typer.Exit(1)

    DebugPresenter.render_test_notification(response)
