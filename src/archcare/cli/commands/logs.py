"""
Logs Typer command for the Archcare CLI.

Defines the `archcare logs` command, a single Typer app with a callback (so it can be invoked as
either `archcare logs` or `archcare logs <task-name>`) that tails the main `archcare.log` or a
task-specific `tasks/<task-name>.log`. Exits with status 1 and a clear message if the requested log
file doesn't exist (e.g., the user hasn't run the task yet, or hasn't run archcare at all).
"""

from typing import Annotated

import typer

from archcare.core.executor import TaskExecutor
from archcare.utils import print_error, print_header

logs_app = typer.Typer()


@logs_app.callback(
    invoke_without_command=True,
    help="""
Show logs for Archcare or a specific task.

Example:
    archcare logs                    # Main logs
    archcare logs failed-services    # Task-specific logs
""",
)
def logs(
    ctx: typer.Context,
    task_name: Annotated[str | None, typer.Argument(help="Task to show logs for")] = None,
    lines: Annotated[int, typer.Option("--lines", "-n", help="Number of lines to show")] = 50,
):
    """
    Show logs for Archcare or a specific task.

    Resolves the requested log file from `~/.local/state/archcare/logs` directory (`archcare.log`
    for the main log, `tasks/<task>.log` per task), prints a header naming the file, and then dumps
    the last `lines` lines. When a subcommand is invoked via Typer, returns early to let it handle
    things; otherwise exits with status 1 if the log file doesn't exist.

    Args:
        ctx (typer.Context): Typer context whose `obj` is an
            [`AppContext`][archcare.cli.context.AppContext].
        task_name (str | None): Optional task name to show logs for; when `None`, shows the main
            `archcare.log`. Defaults to `None`.
        lines (int): Number of trailing log lines to show. Defaults to `50`.
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
