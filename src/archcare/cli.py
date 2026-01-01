"""
Command-line interface for archcare.

Provides commands for running maintenance tasks and viewing status.
"""

from pathlib import Path

import typer
from loguru import logger

from archcare.config import (
    AppSettings,
    ConfigLoader,
    create_default_config_files,
    TasksConfig,
    TaskConfig,
    TaskType,
)
from archcare.core import TaskExecutor, TaskScheduler, TaskStatus
from archcare.tasks import FailedServicesTask
from archcare.utils.output import (
    print_error,
    print_header,
    print_info,
    print_schedule_table,
    print_success,
    print_summary_panel,
    print_task_details,
    print_task_result,
    print_warning,
    console,
)
from archcare.utils.logging import setup_task_logging, setup_logging

# Create Typer app
app = typer.Typer(
    name="archcare",
    help="Arch Linux maintenance task manager",
)

# Global state (initialized in main)
_loader: ConfigLoader | None = None
_settings: AppSettings | None = None
_executor: TaskExecutor | None = None


def get_executor() -> TaskExecutor:
    """
    Get or create the task executor.

    Returns:
        TaskExecutor instance
    """
    global _loader, _settings, _executor

    if _executor is None:
        # Initialize configuration
        if _loader is None:
            _loader = ConfigLoader()

        if _settings is None:
            _settings = _loader.load_settings()
            _settings.ensure_directories()
            setup_logging(_settings)

        # Load state
        state = _loader.load_state()

        # Create executor
        _executor = TaskExecutor(
            config_loader=_loader,
            settings=_settings,
            state=state,
        )

        # Register all available tasks
        _register_tasks(_executor)

    return _executor


def _register_tasks(executor: TaskExecutor) -> None:
    """
    Register all available task implementations.

    Args:
        executor: TaskExecutor to register tasks with
    """
    executor.register_task("failed-services", FailedServicesTask)


def _handle_due_task(executor: TaskExecutor, task_name: str, tasks_config: TasksConfig):
    scheduler = TaskScheduler(tasks_config, executor.state)
    task_schedule_info = scheduler.get_schedule_info(task_name)
    is_due = task_schedule_info.is_due
    reason = task_schedule_info.reason

    if not is_due:
        print_info(f"Task is not due: {reason}")
        if not typer.confirm("Run anyway?"):
            raise typer.Exit(0)


def _handle_task(task_config: TaskConfig | None, task_name: str):
    if not task_config:
        print_error(f"Task not found: {task_name}")
        print_info("Use 'archcare list' to see available tasks")
        raise typer.Exit(1)

    if not task_config.enabled:
        print_warning(f"Task '{task_name}' is disabled in configuration")
        if not typer.confirm("Run anyway?"):
            raise typer.Exit(0)


@app.command()
def run(
    task_name: str = typer.Argument(help="Name of the task to run"),
    force: bool = typer.Option(False, "--force", "-f", help="Run even if not due"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
):
    """
    Run a specific maintenance task.

    Example:
        archcare run failed-services
        archcare run system-update --force
    """
    executor = get_executor()
    if _settings:
        setup_task_logging(task_name, _settings)

    print_header(f"Running Task: {task_name}")

    try:
        # Check if task exists in configuration
        tasks_config = executor.config_loader.load_tasks()
        task_config = tasks_config.get_task(task_name)

        _handle_task(task_config, task_name)

        # Check if task is due (unless --force)
        if not force:
            _handle_due_task(executor, task_name, tasks_config)

        # Execute the task
        logger.info(f"Executing task: {task_name}")
        result = executor.execute_task(task_name)

        # Display result
        print()
        if verbose:
            print_task_details(task_name, result, show_details=True)
        else:
            print_task_result(result, task_name)

        # Exit code based on result
        if result.status == TaskStatus.SUCCESS:
            raise typer.Exit(0)
        elif result.status == TaskStatus.PARTIAL:
            # Partial success - found issues but task completed
            raise typer.Exit(0)
        elif result.status == TaskStatus.SKIPPED:
            raise typer.Exit(0)
        else:  # FAILED
            raise typer.Exit(1)

    except typer.Exit as e:
        if e.exit_code != 0:
            raise

    except Exception as e:
        print_error(f"Failed to run task: {e}")
        logger.exception(f"Error running task {task_name}")
        raise typer.Exit(1)


@app.command()
def status(
    task_name: str | None = typer.Argument(None, help="Specific task to check"),
    due_only: bool = typer.Option(False, "--due", help="Show only due tasks"),
):
    """
    Show status and schedule for tasks.

    Example:
        archcare status                    # All tasks
        archcare status failed-services    # Specific task
        archcare status --due              # Only due tasks
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


@app.command("list")
def list_(
    task_type: str | None = typer.Option(
        None, "--type", "-t", help="Filter by type: automated or manual"
    ),
):
    """
    List all available tasks.

    Example:
        archcare list
        archcare list --type manual
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


@app.command()
def init():
    """
    Initialize archcare configuration files.

    This creates default configuration files if they don't exist.
    """
    config_dir = Path.home() / ".config/archcare"

    print_header("Initializing Archcare")
    print_info(f"Config directory: {config_dir}")

    if config_dir.exists():
        files = list(config_dir.glob("*.toml"))
        if files:
            print_warning("Configuration files already exist:")
            for f in files:
                print(f"  - {f.name}")

            if not typer.confirm("Overwrite existing files?"):
                print_info("Initialization cancelled")
                raise typer.Exit(0)

    # Create config files
    create_default_config_files(config_dir)

    print_success("Configuration initialized!")
    print_info(f"Edit config files in: {config_dir}")
    print_info("Run 'archcare list' to see available tasks")


@app.command()
def logs(
    task_name: str | None = typer.Argument(None, help="Task to show logs for"),
    lines: int = typer.Option(50, "--lines", "-n", help="Number of lines to show"),
):
    """
    Show logs for archcare or a specific task.

    Example:
        archcare logs                    # Main logs
        archcare logs failed-services    # Task-specific logs
    """
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


def main():
    """
    Main entry point for the CLI.
    """
    app()


if __name__ == "__main__":
    main()
