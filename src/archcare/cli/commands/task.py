"""
Task related Typer commands for Archcare.

Defines the `archcare task` sub-app and its three commands — `run`, `status`, `list` — each one a
thin shell that constructs a fresh [TaskService][] from the shared
[AppContext][archcare.cli.context.AppContext] and delegates rendering to [TaskPresenter][].

The same exception set (`InvalidTasksFileError`, `TaskNotFoundError`, `InvalidTaskTypeError`,
`typer.Abort`) recurs in every command, so the presenter's per-error helpers (`empty`, `not_found`,
`invalid_task_type`, `aborted`) are reused across all three.

See also:
    [archcare.services.exceptions][]: The domain exceptions handled by these Typer commands
"""

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
    """
    Build a fresh `TaskService` from the context's executor.

    Args:
        ctx typer.Context: Typer context whose `obj` is an `AppContext`.

    Returns:
        TaskService: New service instance bound to the shared executor.
    """
    return TaskService(ctx.obj.executor)


def _presenter(ctx: typer.Context) -> TaskPresenter:
    """
    Build a fresh `TaskPresenter` from the context's task registry.

    Args:
        ctx (typer.Context): Typer context whose `obj` is an `AppContext`.

    Returns:
        TaskPresenter: New presenter instance bound to the shared task registry.
    """
    return TaskPresenter(ctx.obj.task_registry)


@task_app.command(
    help="""
Run a specific maintenance task.

Example:
    archcare task run failed-services
    archcare task run system-update --force
"""
)
def run(
    ctx: typer.Context,
    task_name: Annotated[str, typer.Argument(help="Name of the task to run")],
    force: Annotated[bool, typer.Option("--force", "-f", help="Run even if not due")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show detailed output")] = False,
):
    """
    Run a specific maintenance task.

    Sets up logging, then delegates to [TaskService.run_task][] and renders the resulting
    [TaskRunResponse][archcare.services.responses.TaskRunResponse] via [TaskPresenter.render_run][].
    Catches `InvalidTasksFileError` (empty file), `TaskNotFoundError`, `typer.Abort`, and a generic
    fallback — each rendered via the matching presenter helper and converted into a non-zero exit.
    The final exit code reflects the task outcome: `0` for success/partial/skipped, `1` for failure.

    Args:
        ctx (typer.Context): Typer context whose `obj` is an
            [AppContext][archcare.cli.context.AppContext].
        task_name (str): Name of the task to run.
        force (bool): Run even if not due. Defaults to `False`.
        verbose (bool): Show detailed (per-task formatter) output. Defaults to `False`.
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


@task_app.command(
    help="""
Show status and schedule for tasks.

Example:
    archcare task status                    # All tasks
    archcare task status failed-services    # Specific task
    archcare task status --due              # Only due tasks
"""
)
def status(
    ctx: typer.Context,
    task_name: Annotated[str | None, typer.Argument(help="Specific task to check")] = None,
    due_only: Annotated[bool, typer.Option("--due", help="Show only due tasks")] = False,
):
    """
    Show status and schedule for tasks.

    Sets up logging, then delegates to [TaskService.get_task_status][] and renders the resulting
    [TaskStatusResponse][archcare.services.responses.TaskStatusResponse] via
    [TaskPresenter.render_status][]. Catches `InvalidTasksFileError` and `TaskNotFoundError` (the
    latter coerced to an empty string when no `task_name` was given) and routes them to the matching
    presenter helper, exiting with status 1.

    Args:
        ctx (typer.Context): Typer context whose `obj` is an
            [AppContext][archcare.cli.context.AppContext].
        task_name (str | None): Specific task to check; when `None` (default), shows status for
            all tasks.
        due_only (bool): When `True`, show only due tasks. Ignored in single-task mode. Defaults
            to `False`.
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


@task_app.command(
    "list",
    help="""
List all available and enabled tasks.

Example:
    archcare task list
    archcare task list --type manual
""",
)
def list_tasks(
    ctx: typer.Context,
    task_type: Annotated[
        str | None,
        typer.Option("--type", "-t", help="Filter by type: automated or manual"),
    ] = None,
):
    """
    List all available and enabled tasks.

    Sets up logging, then delegates to [TaskService.list_tasks][] and renders the resulting
    [TaskListResponse][archcare.services.responses.TaskListResponse] via
    [TaskPresenter.render_list][]. Catches `InvalidTasksFileError` and `InvalidTaskTypeError` and
    routes them to the matching presenter helper, exiting with status 1.

    Args:
        ctx (typer.Context): Typer context whose `obj` is an
            [AppContext][archcare.cli.context.AppContext].
        task_type (str | None): Filter by type — `automated`, `manual`, or `None` for all enabled
            tasks. Defaults to `None`.
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
