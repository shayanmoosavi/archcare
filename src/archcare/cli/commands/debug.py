"""
Typer commands for debugging purposes.

Defines the `archcare debug` sub-app containing the `test-notification` command. Commands stay thin:
they build the service from the shared [`AppContext`][archcare.cli.context.AppContext] and delegate
all business logic to [`DebugService`][] and all terminal output to [`DebugPresenter`][].

Each failure mode (invalid severity, missing libnotify, send failure) is caught and translated into
a presenter call plus a non-zero exit, so calling scripts can detect failures reliably.
"""

from typing import Annotated

import typer

from archcare.cli.presenters import DebugPresenter
from archcare.services import DebugService
from archcare.services.exceptions import (
    InvalidSeverityError,
    NotificationSendError,
    NotificationUnavailableError,
)
from archcare.utils import print_error

debug_app = typer.Typer(help="Debug commands for Archcare.")


@debug_app.command(
    help="""
Test desktop notifications.

Sends a test notification to verify the notification system is working.

Example:
    archcare debug test-notification
    archcare debug test-notification --severity critical
"""
)
def test_notification(
    ctx: typer.Context,
    severity: Annotated[
        str,
        typer.Option("--severity", "-s", help="Notification severity: critical, warning, or info"),
    ] = "warning",
):
    """
    Test desktop notifications.

    Sets up logging, then constructs a fresh [`DebugService`][] from the context's
    [`NotificationManager`][archcare.core.notifications.NotificationManager] and dispatches a test
    notification at the requested severity. Any service-layer error (invalid severity, missing
    libnotify, send failure, or unexpected exception) is rendered via the matching
    [`DebugPresenter`][] helper and the process exits with status 1. On success, the renderer's
    success path is shown.

    Args:
        ctx (typer.Context): Typer context whose `obj` is an
            [`AppContext`][archcare.cli.context.AppContext].
        severity (str): Notification severity — one of `critical`, `warning`, or `info`. Defaults
            to `warning`.
    """
    ctx.obj.setup_logging()
    DebugPresenter.header()

    try:
        response = DebugService(ctx.obj.executor.notification_manager).test_notification(severity)
    except InvalidSeverityError as e:
        DebugPresenter.invalid_severity(e)
        raise typer.Exit(1) from e
    except NotificationUnavailableError as e:
        DebugPresenter.notification_unavailable()
        raise typer.Exit(1) from e
    except NotificationSendError as e:
        DebugPresenter.notification_send_failed()
        raise typer.Exit(1) from e
    except Exception as e:
        print_error(str(e))
        raise typer.Exit(1) from e

    DebugPresenter.render_test_notification(response)
