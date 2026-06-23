"""Typer CLI interface for Archcare."""

from os import getenv

import typer

from archcare.cli.commands import debug_app, logs_app, setup_app, task_app
from archcare.cli.context import AppContext
from archcare.services.exceptions import ConfigNotInitializedError
from archcare.utils.output import print_error, print_info

app = typer.Typer(
    name="archcare",
    help="Arch Linux maintenance task manager",
)

app.add_typer(task_app, name="task")
app.add_typer(setup_app, name="setup")
app.add_typer(logs_app, name="logs")
app.add_typer(debug_app, name="debug")


@app.callback()
def callback(
    ctx: typer.Context,
    devel: bool = typer.Option(
        False,
        "--devel",
        help="Enable verbose console output (development mode)",
        is_eager=True,
    ),
) -> None:
    # ARCHCARE_USER is set by the systemd service unit; its absence means
    # an interactive invocation.
    user = getenv("ARCHCARE_USER")
    ctx.obj = AppContext(devel=devel, user=user)


def main():
    """
    Main entry point for the CLI.
    """
    try:
        app()
    except ConfigNotInitializedError as e:
        print_error(str(e))
        print_info("Run 'archcare setup config' to get started.")
        typer.Exit(1)


if __name__ == "__main__":
    main()
