"""
Task executor for archcare.

Handles task instantiation and execution coordination.
"""

from datetime import datetime, timedelta

import typer
from loguru import logger
import os

from archcare.config import (
    AppSettings,
    AppState,
    ConfigLoader,
    TaskConfig,
    TaskType,
    SkipReason,
    TasksConfig,
)
from archcare.core.scheduler import TaskScheduler
from archcare.tasks.base import BaseTask
from archcare.utils import is_root, change_ownership_to_user
from archcare.utils.output import print_info, print_warning

from .models import TaskResult, skipped


class TaskExecutor:
    """
    Coordinates task execution and state management.

    This class:
    - Instantiates tasks from their configuration
    - Manages task execution lifecycle
    - Updates task state after execution
    - Determines when tasks are due to run
    """

    def __init__(
        self,
        config_loader: ConfigLoader,
        settings: AppSettings,
        state: AppState,
        task_registry: dict[str, type[BaseTask]] | None = None,
    ):
        """
        Initialize task executor.

        Args:
            config_loader: ConfigLoader for loading configurations
            settings: Application settings
            state: Application state (for tracking runs)
            task_registry: Map of command name to task class
                          This will be populated as we implement tasks
        """
        self.config_loader = config_loader
        self.settings = settings
        self.state = state
        self.task_registry = task_registry or {}

    def register_task(self, command: str, task_class: type[BaseTask]) -> None:
        """
        Register a task class for a command.

        Args:
            command: Command identifier (e.g., "failed-services")
            task_class: Task class that handles this command

        Example:
            executor.register_task("failed-services", FailedServicesTask)
        """
        self.task_registry[command] = task_class
        logger.debug(f"Registered task: {command} -> {task_class.__name__}")

    def _create_task(self, task_config: TaskConfig) -> BaseTask:
        """
        Create a task instance from its configuration.

        Args:
            task_config: Task configuration

        Returns:
            Instantiated task object

        Raises:
            ValueError: If task command is not registered
        """
        task_class = self.task_registry.get(task_config.command)

        if not task_class:
            raise ValueError(
                f"No task registered for command: {task_config.command}. "
                f"Available commands: {list(self.task_registry.keys())}"
            )

        return task_class(config=task_config, settings=self.settings)

    def execute_task(self, task_name: str, force: bool = False) -> TaskResult:
        """
        Execute a single task by name.

        Args:
            task_name: Name of the task to execute
            force: Whether to force running the task. It skips

        Returns:
            TaskResult from task execution

        Raises:
            ValueError: If task is not found
        """
        # Load task configuration
        tasks_config = self.config_loader.load_tasks()
        task_config = tasks_config.get_task(task_name)

        # Won't happen due to _handle_task function in cli.py, but being defensive
        if not task_config:
            raise ValueError(f"Task not found: {task_name}")

        is_systemd = self.settings.user is not None
        if not force:
            handle_disabled_result = self._handle_disabled_task(
                task_name, task_config, is_systemd
            )
            if handle_disabled_result:
                self._update_state(task_config, handle_disabled_result)
                return handle_disabled_result

            handle_due_result = self._handle_due_task(
                task_name, tasks_config, is_systemd
            )
            if handle_due_result:
                self._update_state(task_config, handle_due_result)
                return handle_due_result

        # Create and run task
        task = self._create_task(task_config)
        result = task.run()

        # Update state
        self._update_state(task_config, result)

        return result

    def _handle_disabled_task(
        self, task_name: str, task_config: TaskConfig, is_systemd: bool = False
    ) -> TaskResult | None:
        is_interactive = not is_systemd

        if not task_config.enabled:
            print_warning(
                f"Task '{task_name}' is disabled in configuration", is_interactive
            )
            task = self._create_task(task_config)
            task.set_start_time()
            if is_systemd:
                return task.create_result(
                    skipped(
                        "Task run from systemd timer will not be interactive",
                        SkipReason.DISABLED,
                    )
                )
            else:
                return (
                    task.create_result(
                        skipped("Cancelled by user", SkipReason.USER_CANCELLED)
                    )
                    if not typer.confirm("Run anyway?")
                    else None
                )
        else:
            return None

    def _handle_due_task(
        self, task_name: str, tasks_config: TasksConfig, is_systemd: bool = False
    ) -> TaskResult | None:
        scheduler = TaskScheduler(tasks_config, self.state)
        task_schedule_info = scheduler.get_schedule_info(task_name)
        is_due = task_schedule_info.is_due
        reason = task_schedule_info.reason
        task_config = tasks_config.get_task(task_name)
        is_interactive = not is_systemd

        if not is_due:
            print_info(f"Task is not due: {reason}", is_interactive)
            task = self._create_task(task_config)
            task.set_start_time()
            if is_systemd:
                logger.info(f"Skipping the execution of task {task_name}")
                return task.create_result(
                    skipped(
                        "Task run from systemd timer will not be interactive",
                        SkipReason.NOT_DUE,
                    )
                )
            else:
                logger.info(f"Skipping the execution of task {task_name}")
                return (
                    task.create_result(
                        skipped(
                            "Cancelling task execution as requested by user",
                            SkipReason.USER_CANCELLED,
                        )
                    )
                    if not typer.confirm("Run anyway?")
                    else None
                )
        else:
            return None

    def execute_all(self, task_type: TaskType | None = None) -> dict[str, TaskResult]:
        """
        Execute all enabled tasks, optionally filtered by type.

        Args:
            task_type: Filter by "automated" or "manual" (None = all)

        Returns:
            Dictionary mapping task names to their results

        Reason for returning dict instead of list:
        - Easy lookup of specific task results
        - Preserves task names with results
        - Better for error reporting and logging
        """
        tasks_config = self.config_loader.load_tasks()

        # Get tasks to execute
        if task_type:
            tasks_to_run = tasks_config.get_tasks_by_type(task_type.value)
        else:
            tasks_to_run = tasks_config.get_enabled_tasks()

        logger.info(f"Executing {len(tasks_to_run)} tasks")

        results = {}
        for task_name, task_config in tasks_to_run.items():
            try:
                logger.info(f"Running task: {task_name}")
                result = self.execute_task(task_name)
                results[task_name] = result
            except Exception as e:
                logger.error(f"Failed to execute task {task_name}: {e}")
                # Continue with other tasks even if one fails
                # (unless it's an unrecoverable error)

        return results

    def get_due_tasks(self) -> dict[str, TaskConfig]:
        """
        Get all tasks that are currently due to run.

        Returns:
            Dictionary of task names to their configurations
        """
        from archcare.core.scheduler import TaskScheduler

        tasks_config = self.config_loader.load_tasks()
        scheduler = TaskScheduler(tasks_config, self.state)

        # Get schedule info from scheduler
        due_schedule_info = scheduler.get_due_tasks()

        # Convert to dict of TaskConfig for execution purposes
        due_tasks = {}
        for info in due_schedule_info:
            task_config = tasks_config.get_task(info.task_name)
            if task_config:
                due_tasks[info.task_name] = task_config

        return due_tasks

    def _update_state(self, task_config: TaskConfig, result: TaskResult):
        """
        Update task state after execution.

        Args:
            task_config: Configuration of executed task
            result: Result from task execution

        Reason for private method:
        - Keeps state management logic centralized
        - Automatically calculates next due date
        - Ensures state is always updated after execution
        """
        # Calculate next due date
        next_due = datetime.now() + timedelta(days=task_config.frequency)

        # Storing the current next due for skipped task
        next_due_skipped = self.state.get_task_state(task_config.name).next_due
        result_skipped = result.is_skipped()

        # Update state
        self.state.update_task_state(
            task_name=task_config.name,
            status=result.status,
            next_due=next_due if not result_skipped else next_due_skipped,
            error=str(result.error) if result.error else None,
            skip_reason=result.skip_reason,
            skip_message=result.skip_message,
        )

        # Save state to disk
        self.config_loader.save_state(self.state)

        # Change ownership if running as root via systemd
        user = os.environ.get("ARCHCARE_USER")
        if is_root() and user:
            state_file = self.settings.state_file
            change_ownership_to_user(state_file, user)
            change_ownership_to_user(state_file.parent, user)

        logger.debug(f"Updated state for {task_config.name}: next due {next_due}")
