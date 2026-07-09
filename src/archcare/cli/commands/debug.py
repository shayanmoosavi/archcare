"""Typer commands for debugging purposes."""

from typing import Annotated

import typer

from archcare.cli.presenters import DebugPresenter
from archcare.services import DebugService
from archcare.services.exceptions import (
    InvalidSeverityError,
    NotificationSendError,
    NotificationUnavailableError,
)
from archcare.utils.output import print_error

debug_app = typer.Typer(help="Debug commands for Archcare.")


@debug_app.command()
def test_notification(
    ctx: typer.Context,
    severity: Annotated[
        str,
        typer.Option(
            "--severity", "-s", help="Notification severity: critical, warning, or info"
        ),
    ] = "warning",
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
    except Exception as e:
        print_error(str(e))
        raise typer.Exit(1)

    DebugPresenter.render_test_notification(response)
