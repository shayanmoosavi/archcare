"""Task related Typer commands for Archcare."""

from os import getenv

from loguru import logger
import typer

from archcare.cli._state import get_executor

from archcare.cli.presenters.task_presenter import TaskPresenter
from archcare.services.exceptions import InvalidTaskTypeError, TaskNotFoundError
from archcare.services.task_service import TaskService

task_app = typer.Typer(help="Run and manage maintenance tasks.")


def _service() -> TaskService:
    return TaskService(get_executor(getenv("ARCHCARE_USER")))


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
    try:
        response = _service().run_task(task_name, force)
    except TaskNotFoundError:
        TaskPresenter.not_found(task_name)
        raise typer.Exit(1)
    except typer.Abort:
        TaskPresenter.aborted(task_name)
        raise typer.Exit(1)
    except Exception as e:
        # is_interactive isn't known here since the error happened before
        # the service could compute it - default to interactive formatting.
        TaskPresenter.error(f"Failed to run task: {e}")
        logger.exception(f"Error running task {task_name}")
        raise typer.Exit(1)

    TaskPresenter.render_run(response, verbose=verbose)

    outcome = response.outcome
    if outcome.is_success() or outcome.is_partial() or outcome.is_skipped():
        raise typer.Exit(0)
    # Task failed if we got here
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
    try:
        response = _service().get_task_status(task_name, due_only)
    except TaskNotFoundError as e:
        TaskPresenter.error(str(e))
        raise typer.Exit(1)

    TaskPresenter.render_status(response)


@task_app.command("list")
def list_tasks(
    task_type: str | None = typer.Option(
        None, "--type", "-t", help="Filter by type: automated or manual"
    ),
):
    """
    List all available and enabled tasks.

    Example:
        archcare task list
        archcare task list --type manual
    """
    try:
        response = _service().list_tasks(task_type)
    except InvalidTaskTypeError:
        TaskPresenter.invalid_task_type()
        raise typer.Exit(1)

    TaskPresenter.render_list(response)
