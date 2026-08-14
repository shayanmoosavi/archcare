"""Task related Typer commands for Archcare."""

from typing import Annotated

import typer

from archcare.cli.presenters import TaskPresenter
from archcare.services import TaskService
from archcare.services.exceptions import (
    InvalidTasksFileError,
    InvalidTaskTypeError,
    TaskNotFoundError,
)

task_app = typer.Typer(help="Run and manage maintenance tasks.")


def _service(ctx: typer.Context) -> TaskService:
    return TaskService(ctx.obj.executor)


def _presenter(ctx: typer.Context) -> TaskPresenter:
    return TaskPresenter(ctx.obj.task_registry)


@task_app.command()
def run(
    ctx: typer.Context,
    task_name: Annotated[str, typer.Argument(help="Name of the task to run")],
    force: Annotated[
        bool, typer.Option("--force", "-f", help="Run even if not due")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Show detailed output")
    ] = False,
):
    """
    Run a specific maintenance task.

    Example:
        archcare task run failed-services
        archcare task run system-update --force
    """
    ctx.obj.setup_logging()
    presenter = _presenter(ctx)

    try:
        response = _service(ctx).run_task(task_name, force)
    except InvalidTasksFileError as e:
        presenter.empty()
        raise typer.Exit(1) from e
    except TaskNotFoundError as e:
        presenter.not_found(task_name)
        raise typer.Exit(1) from e
    except typer.Abort as e:
        presenter.aborted(task_name)
        raise typer.Exit(1) from e
    except Exception as e:
        # is_interactive isn't known here since the error happened before
        # the service could compute it - default to interactive formatting.
        presenter.error(f"Failed to run task {repr(task_name)}: {e}")
        raise typer.Exit(1) from e

    presenter.render_run(response, settings=ctx.obj.settings, verbose=verbose)

    outcome = response.outcome
    if outcome.is_success() or outcome.is_partial() or outcome.is_skipped():
        raise typer.Exit(0)
    # Task failed if we got here
    raise typer.Exit(1)


@task_app.command()
def status(
    ctx: typer.Context,
    task_name: Annotated[str | None, typer.Argument(help="Specific task to check")] = None,
    due_only: Annotated[bool, typer.Option("--due", help="Show only due tasks")] = False,
):
    """
    Show status and schedule for tasks.

    Example:
        archcare task status                    # All tasks
        archcare task status failed-services    # Specific task
        archcare task status --due              # Only due tasks
    """
    ctx.obj.setup_logging()
    presenter = _presenter(ctx)

    try:
        response = _service(ctx).get_task_status(task_name, due_only)
    except InvalidTasksFileError as e:
        presenter.empty()
        raise typer.Exit(1) from e
    except TaskNotFoundError as e:
        presenter.not_found(task_name or "")
        raise typer.Exit(1) from e
    except Exception as e:
        presenter.error(str(e))
        raise typer.Exit(1) from e

    presenter.render_status(response)


@task_app.command("list")
def list_tasks(
    ctx: typer.Context,
    task_type: Annotated[
        str | None,
        typer.Option("--type", "-t", help="Filter by type: automated or manual"),
    ] = None,
):
    """
    List all available and enabled tasks.

    Example:
        archcare task list
        archcare task list --type manual
    """
    ctx.obj.setup_logging()
    presenter = _presenter(ctx)

    try:
        response = _service(ctx).list_tasks(task_type)
    except InvalidTasksFileError as e:
        presenter.empty()
        raise typer.Exit(1) from e
    except InvalidTaskTypeError as e:
        presenter.invalid_task_type()
        raise typer.Exit(1) from e

    presenter.render_list(response)
