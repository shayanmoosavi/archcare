"""Task service for handling task related operations."""

from os import getenv

from loguru import logger

from archcare.config import TaskType
from archcare.core import TaskExecutor, TaskScheduler
from archcare.services.exceptions import (
    InvalidTaskTypeError,
    TaskNotFoundError,
    TasksFileEmptyError,
)
from archcare.services.responses import (
    TaskListResponse,
    TaskRunResponse,
    TaskStatusResponse,
)


class TaskService:
    """Business logic for the `task` command group."""

    def __init__(self, executor: TaskExecutor) -> None:
        self._executor = executor

    def run_task(self, task_name: str, force: bool = False) -> TaskRunResponse:
        """
        Execute a maintenance task.

        Args:
            task_name: Name of the task to run
            force: Whether to run even if not due

        Raises:
            TasksFileEmptyError: If the tasks file is empty.
            TaskNotFoundError: If `task_name` is not in the task configuration.
        """
        tasks_config = self._executor.config_loader.load_tasks()
        if not tasks_config.tasks:
            raise TasksFileEmptyError()
        try:
            tasks_config.get_task(task_name)
        except ValueError:
            raise TaskNotFoundError(task_name)

        # ARCHCARE_USER is set by the systemd unit; its absence means the user is
        # running the command interactively.
        is_interactive = getenv("ARCHCARE_USER") is None

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

        Args:
            task_type: Optional type to filter tasks by (one of 'automated' or 'manual')

        Raises:
            TasksFileEmptyError: If the tasks file is empty.
            InvalidTaskTypeError: If `task_type` is set but not 'automated' or 'manual'.
        """
        tasks_config = self._executor.config_loader.load_tasks()
        if not tasks_config.tasks:
            raise TasksFileEmptyError()

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

        Args:
            task_name: Optional name of a single task to get status for
                      (default: None, meaning all tasks)
            due_only: Whether to include only tasks that are currently due
                      (default: False)

        Raises:
            TasksFileEmptyError: If the tasks file is empty.
            TaskNotFoundError: If `task_name` is set but unknown.
        """
        tasks_config = self._executor.config_loader.load_tasks()
        if not tasks_config.tasks:
            raise TasksFileEmptyError()
        scheduler = TaskScheduler(tasks_config, self._executor.state)

        if task_name:
            try:
                info = scheduler.get_schedule_info(task_name)
            except ValueError:
                raise TaskNotFoundError(task_name)

            return TaskStatusResponse(schedule_info=[info])

        schedule_info = (
            scheduler.get_due_tasks() if due_only else scheduler.get_all_schedule_info()
        )
        summary = scheduler.get_maintenance_summary()

        return TaskStatusResponse(
            schedule_info=schedule_info, summary=summary, due_only=due_only
        )
