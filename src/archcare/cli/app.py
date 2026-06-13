"""Typer CLI interface for Archcare."""

import typer

from archcare.cli.commands import task_app, setup_app, logs_app, debug_app
from archcare.cli import _state

app = typer.Typer(
    name="archcare",
    help="Arch Linux maintenance task manager",
)

app.add_typer(task_app, name="task")
app.add_typer(setup_app, name="setup")
app.add_typer(logs_app)
app.add_typer(debug_app, name="debug")


@app.callback()
def devel_mode(
    devel: bool = typer.Option(
        False,
        "--devel",
        help="Enable verbose console output (development mode)",
        is_eager=True,
    ),
) -> None:
    _state._devel = devel


def main():
    """
    Main entry point for the CLI.
    """
    app()


if __name__ == "__main__":
    main()
