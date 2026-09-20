"""
Task service for handling task related operations.

Contains [`TaskService`][], the business logic behind the `archcare task` command group:

- `run_task()`: Execute a single maintenance task via the [`TaskExecutor`][] and report its outcome.
- `list_tasks()`: Enumerate tasks from configuration, optionally filtered by type (`automated` /
    `manual`) or reduced to enabled tasks.
- `get_task_status()`: Report scheduling status — due dates, overdue state, and a system-wide
    maintenance summary — via the [`TaskScheduler`][].

Every public method returns a response DTO from [`archcare.services.responses`][] so the CLI layer
never handles raw business state, and translates low-level [`UnknownTaskError`][] into the
service-layer [`TaskNotFoundError`][].

See Also:
    - [`archcare.services.exceptions`][]: Service-layer error hierarchy used here
    - [`archcare.cli.commands.task`][]: CLI commands delegating to this service
"""

from loguru import logger

from archcare.config import TaskType
from archcare.config.exceptions import UnknownTaskError
from archcare.core import TaskScheduler
from archcare.core.executor import TaskExecutor
from archcare.services.exceptions import (
    InvalidTasksFileError,
    InvalidTaskTypeError,
    TaskNotFoundError,
)
from archcare.services.responses import (
    TaskListResponse,
    TaskRunResponse,
    TaskStatusResponse,
)


class TaskService:
    """
    Business logic for the `task` command group.

    Acts as the high-level facade over task execution and scheduling: validates task configuration
    before touching it, delegates the heavy lifting to [`TaskExecutor`][] (execution) and
    [`TaskScheduler`][] (scheduling), and packages results into response DTOs for the
    CLI presenters.
    """

    def __init__(self, executor: TaskExecutor) -> None:
        """
        Initialize the task service.

        Args:
            executor (TaskExecutor): Executor built once per invocation by the application context
                and shared across services.
        """
        self._executor = executor

    def run_task(self, task_name: str, force: bool = False) -> TaskRunResponse:
        """
        Execute a maintenance task.

        Validates the task exists in configuration (raising early if the tasks file is empty or the
        name is unknown), then delegates to the executor's full run pipeline (`pre_check` →
        `should_run` → `execute` → `post_execute`, plus state updates). Use `force=True` to bypass
        the due-date check.

        Args:
            task_name (str): Name of the task to run.
            force (bool): Whether to run even if not due. Defaults to `False` (the task may be
                reported as skipped).

        Returns:
            TaskRunResponse: The task's [`TaskResult`][archcare.core.models.TaskResult] outcome and
                whether the invocation was interactive (user terminal vs. systemd timer).

        Raises:
            InvalidTasksFileError: If the tasks file is empty or invalid.
            TaskNotFoundError: If `task_name` is not in the task configuration.

        Side Effects:
            Runs the task (potentially invoking system commands with sudo) and persists updated
                state (`last_run`, `next_due`, `status`) to `state.json`.
        """
        tasks_config = self._executor.config_loader.load_tasks()
        if not tasks_config.tasks:
            raise InvalidTasksFileError()
        try:
            tasks_config.get_task(task_name)
        except UnknownTaskError as e:
            raise TaskNotFoundError(task_name) from e

        # Whether the task is being run interactively by user or via systemd timer
        is_interactive = self._executor.user_context.is_interactive

        logger.info(f"Executing task: {task_name}")
        outcome = self._executor.execute_task(task_name, force)

        return TaskRunResponse(
            task_name=task_name,
            outcome=outcome,
            is_interactive=is_interactive,
        )

    def list_tasks(self, task_type: str | None = None) -> TaskListResponse:
        """
        List tasks, optionally filtered by type.

        Matching is exact against the [`TaskType`][] values; when no filter is given, only *enabled*
        tasks are returned.

        Args:
            task_type (str | None): Optional type to filter tasks by — one of `'automated'` or
                `'manual'`. `None` (default) means no type filter, returning enabled tasks of
                all types.

        Returns:
            TaskListResponse: Matching tasks keyed by name, plus the filter that was applied (`None`
                when unfiltered).

        Raises:
            InvalidTasksFileError: If the tasks file is empty or invalid.
            InvalidTaskTypeError: If `task_type` is set but not 'automated' or 'manual'.
        """
        tasks_config = self._executor.config_loader.load_tasks()
        if not tasks_config.tasks:
            raise InvalidTasksFileError()

        match task_type:
            case TaskType.AUTOMATED.value:
                tasks = tasks_config.get_tasks_by_type("automated")
            case TaskType.MANUAL.value:
                tasks = tasks_config.get_tasks_by_type("manual")
            case None:
                tasks = tasks_config.get_enabled_tasks()
            case _:
                raise InvalidTaskTypeError(task_type)

        return TaskListResponse(tasks=tasks, filtered_by=task_type)

    def get_task_status(
        self, task_name: str | None = None, due_only: bool = False
    ) -> TaskStatusResponse:
        """
        Get schedule status for one task, or all tasks.

        Single-task mode (`task_name` set) returns just that task's schedule info. Overview mode
        (`task_name=None`) returns schedule info for all tasks — restricted to currently-due tasks
        when `due_only=True` — plus an at-a-glance `summary` of maintenance counts by category.

        Args:
            task_name (str | None): Optional name of a single task to get status for. `None`
                (default) means all tasks. Defaults to `None`.
            due_only (bool): Whether to include only tasks that are currently due. Ignored in
                single-task mode. Defaults to `False`.

        Returns:
            TaskStatusResponse: Schedule info entries, the maintenance summary (overview mode only),
                and the `due_only` flag.

        Raises:
            InvalidTasksFileError: If the tasks file is empty or invalid.
            TaskNotFoundError: If `task_name` is set but unknown.

        See Also:
            [`TaskScheduler`][]: Source of all schedule computations used here.
        """
        tasks_config = self._executor.config_loader.load_tasks()
        if not tasks_config.tasks:
            raise InvalidTasksFileError()
        scheduler = TaskScheduler(tasks_config, self._executor.state)

        if task_name:
            try:
                info = scheduler.get_schedule_info(task_name)
            except UnknownTaskError as e:
                raise TaskNotFoundError(task_name) from e

            return TaskStatusResponse(schedule_info=[info])

        schedule_info = scheduler.get_due_tasks() if due_only else scheduler.get_all_schedule_info()
        summary = scheduler.get_maintenance_summary()

        return TaskStatusResponse(schedule_info=schedule_info, summary=summary, due_only=due_only)
