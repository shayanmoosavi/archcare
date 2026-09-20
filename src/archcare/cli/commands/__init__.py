"""
The defined Typer sub-apps for the Archcare CLI.

This package exports the four command-group sub-apps that are mounted onto
the root `typer.Typer` instance in [`archcare.cli.app`][]:

- `task_app`: `archcare task` — run, status, list
- `setup_app`: `archcare setup` — config, timers
- `logs_app`: `archcare logs` — main or per-task logs
- `debug_app`: `archcare debug` — test notifications

Each sub-app lives in its own module and follows the same pattern: construct the service from
[`AppContext`][archcare.cli.context.AppContext], delegate business logic to the service layer,
and render via the corresponding presenter.

Modules:
    task: `task` command group
    setup: `setup` command group
    logs: `logs` command group
    debug: `debug` command group

See also:
    - [`archcare.services`][]: The service layer responsible for communicating between CLI and
        business logic
    - [`archcare.cli.presenters`][]: The CLI presenters responsible for rendering results to console
"""

from .debug import debug_app
from .logs import logs_app
from .setup import setup_app
from .task import task_app

__all__ = ["task_app", "setup_app", "logs_app", "debug_app"]
