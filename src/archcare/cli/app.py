"""Typer CLI interface for Archcare."""

import typer

from archcare.cli.commands import task_app
from archcare.cli import _state

app = typer.Typer(
    name="archcare",
    help="Arch Linux maintenance task manager",
)

app.add_typer(task_app, name="task", help="Run and manage maintenance tasks.")


@app.callback()
def devel_mode(
    devel: bool = typer.Option(
        False,
        "--devel",
        help="Enable verbose console output (development mode)",
        is_eager=True,
    ),
) -> None:
    """Arch Linux maintenance task manager."""
    _state._devel = devel


def main():
    """
    Main entry point for the CLI.
    """
    app()


if __name__ == "__main__":
    main()
