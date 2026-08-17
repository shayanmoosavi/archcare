"""Logs Typer command for Archcare cli."""

from typing import Annotated

import typer

from archcare.core.executor import TaskExecutor
from archcare.utils import print_error, print_header

logs_app = typer.Typer()


@logs_app.callback(invoke_without_command=True)
def logs(
    ctx: typer.Context,
    task_name: Annotated[str | None, typer.Argument(help="Task to show logs for")] = None,
    lines: Annotated[int, typer.Option("--lines", "-n", help="Number of lines to show")] = 50,
):
    """
    Show logs for Archcare or a specific task.

    Example:
        archcare logs                    # Main logs
        archcare logs failed-services    # Task-specific logs
    """
    if ctx.invoked_subcommand is not None:
        return  # a subcommand was given, let it handle things
    ctx.obj.setup_logging()
    executor: TaskExecutor = ctx.obj.executor

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
    with open(log_file) as f:
        all_lines = f.readlines()
        recent_lines = all_lines[-lines:]

    for line in recent_lines:
        print(line.rstrip())
