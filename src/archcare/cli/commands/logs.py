"""Logs Typer command for Archcare cli."""

import typer

from archcare.cli._state import get_executor
from archcare.utils.output import print_error, print_header

logs_app = typer.Typer()


@logs_app.callback(invoke_without_command=True)
def logs(
    ctx: typer.Context,
    task_name: str | None = typer.Argument(None, help="Task to show logs for"),
    lines: int = typer.Option(50, "--lines", "-n", help="Number of lines to show"),
):
    """
    Show logs for Archcare or a specific task.

    Example:
        archcare logs                    # Main logs
        archcare logs failed-services    # Task-specific logs
    """
    if ctx.invoked_subcommand is not None:
        return  # a subcommand was given, let it handle things
    executor = get_executor()

    if task_name:
        # Show task logs
        log_file = executor.settings.log_dir / "tasks" / f"{task_name}.log"
    else:
        # Show main logs
        log_file = executor.settings.log_dir / "archcare.log"

    if not log_file.exists():
        print_error(f"Log file not found: {log_file}")
        raise typer.Exit(1)

    print_header(f"Logs: {log_file.name}")

    # Read last N lines
    with open(log_file, "r") as f:
        all_lines = f.readlines()
        recent_lines = all_lines[-lines:]

    for line in recent_lines:
        print(line.rstrip())
