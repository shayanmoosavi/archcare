"""Task related Typer commands for Archcare."""

import os

from loguru import logger
import typer

from archcare.cli._state import get_executor, validate_task_name
from archcare.config import TaskType
from archcare.core import TaskScheduler
from archcare.utils.output import (
    print_header,
    print_error,
    print_task_details,
    print_task_result,
    print_schedule_table,
    print_success,
    print_summary_panel,
    print_info,
    console,
)

task_app = typer.Typer(help="Run and manage maintenance tasks.")


@task_app.command()
def run(
    task_name: str = typer.Argument(help="Name of the task to run"),
    force: bool = typer.Option(False, "--force", "-f", help="Run even if not due"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
):
    """
    Run a specific maintenance task.

    Example:
        archcare task run failed-services
        archcare task run system-update --forcetask
    """
    # Getting the user from environment variable set by systemd service (if running as root) or default to current user
    user = os.getenv("ARCHCARE_USER")

    # Determine if running from systemd (root) or interactively (normal user)
    is_interactive = user is None

    executor = get_executor(user)

    print_header(f"Running Task: {task_name}", is_interactive)

    try:
        # Check if task exists in configuration
        tasks_config = executor.config_loader.load_tasks()

        validate_task_name(task_name, tasks_config)

        # Execute the task
        logger.info(f"Executing task: {task_name}")
        result = executor.execute_task(task_name, force)

        # Display result
        print()
        if verbose:
            print_task_details(
                task_name, result, show_details=True, is_interactive=is_interactive
            )
        else:
            print_task_result(result, task_name, is_interactive)

        # Exit code based on result
        if result.is_success():
            raise typer.Exit(0)
        elif result.is_partial():
            # Partial success - found issues but task completed
            raise typer.Exit(0)
        elif result.is_skipped():
            raise typer.Exit(0)
        else:  # FAILED
            raise typer.Exit(1)

    except typer.Exit as e:
        if e.exit_code != 0:
            raise

    except Exception as e:
        print_error(f"Failed to run task: {e}", is_interactive)
        logger.exception(f"Error running task {task_name}")
        raise typer.Exit(1)


@task_app.command()
def status(
    task_name: str | None = typer.Argument(None, help="Specific task to check"),
    due_only: bool = typer.Option(False, "--due", help="Show only due tasks"),
):
    """
    Show status and schedule for tasks.

    Example:
        archcare task status                    # All tasks
        archcare task status failed-services    # Specific task
        archcare task status --due              # Only due tasks
    """
    executor = get_executor()
    tasks_config = executor.config_loader.load_tasks()
    scheduler = TaskScheduler(tasks_config, executor.state)

    if task_name:
        # Show specific task
        print_header(f"Task Status: {task_name}")

        try:
            info = scheduler.get_schedule_info(task_name)
            print_schedule_table([info])
        except ValueError as e:
            print_error(str(e))
            raise typer.Exit(1)

    else:
        # Show all tasks or just due tasks
        print_header("Task Status")

        if due_only:
            schedule_info = scheduler.get_due_tasks()
            if not schedule_info:
                print_success("No tasks currently due!")
                raise typer.Exit(0)
        else:
            schedule_info = scheduler.get_all_schedule_info()

        print_schedule_table(schedule_info)

        # Show summary
        summary = scheduler.get_maintenance_summary()
        print()
        print_summary_panel("Summary", summary)


@task_app.command("list")
def list_tasks(
    task_type: str | None = typer.Option(
        None, "--type", "-t", help="Filter by type: automated or manual"
    ),
):
    """
    List all available tasks.

    Example:
        archcare task list
        archcare task list --type manual
    """
    executor = get_executor()
    tasks_config = executor.config_loader.load_tasks()

    print_header("Available Tasks")

    # Get tasks
    tasks = {}
    match task_type:
        case TaskType.AUTOMATED.value:
            tasks = tasks_config.get_tasks_by_type("automated")
        case TaskType.MANUAL.value:
            tasks = tasks_config.get_tasks_by_type("manual")
        case None:
            tasks = tasks_config.tasks
        case _:
            print_error("Type must be 'automated' or 'manual'")
            raise typer.Exit(1)

    if not tasks:
        print_info("No tasks found")
        raise typer.Exit(0)

    # Display tasks
    for name, config in tasks.items():
        status_icon = "✓" if config.enabled else "✗"
        type_badge = f"[cyan]{config.task_type.value}[/cyan]"
        freq = f"every {config.frequency} days"

        console.print(f"{status_icon} [bold]{name}[/bold] {type_badge} ({freq})")
        console.print(f"  {config.description}")
        print()
