"""
Task executor for archcare.

Handles task instantiation and execution coordination.
"""

from datetime import datetime, timedelta
from os import getenv

from loguru import logger

from archcare.config import (
    AppSettings,
    AppState,
    ConfigLoader,
    SkipReason,
    TaskConfig,
    TasksConfig,
    TaskStatus,
)
from archcare.core.interaction import NonInteractive, TaskInteraction
from archcare.core.scheduler import TaskScheduler
from archcare.tasks.base import BaseTask
from archcare.utils import change_ownership_to_user, is_root

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
        interaction: TaskInteraction | None = None,
    ):
        """
        Initialize task executor.

        Args:
            config_loader: ConfigLoader for loading configurations
            settings: Application settings
            state: Application state (for tracking runs)
            task_registry: Map of command name to task class
            interaction: Port for user notifications/confirmations during execution
             (e.g. "task is disabled, run anyway?"). Defaults to NonInteractive,
            which never confirms - safe for systemd and tests.
        """
        self.config_loader = config_loader
        self.settings = settings
        self.state = state
        self.task_registry = task_registry or {}
        self.interaction = interaction or NonInteractive()

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

        if not task_config.enabled:
            self.interaction.notify(
                f"Task '{task_name}' is disabled in configuration", level="warning"
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
                    if not self.interaction.confirm("Run anyway?")
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

        if not is_due:
            self.interaction.notify(f"Task is not due: {reason}")
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
                    if not self.interaction.confirm("Run anyway?")
                    else None
                )
        else:
            return None

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

        next_due = self._calculate_next_due(result, task_config)

        # Update state
        self.state.update_task_state(
            task_name=task_config.name,
            status=result.status,
            next_due=next_due,
            error=str(result.error) if result.error else None,
            skip_reason=result.skip_reason,
            skip_message=result.skip_message,
        )

        # Save state to disk
        self.config_loader.save_state(self.state)

        # Change ownership if running as root via systemd
        user = getenv("ARCHCARE_USER")
        if is_root() and user:
            state_file = self.settings.state_file
            change_ownership_to_user(state_file, user)
            change_ownership_to_user(state_file.parent, user)

        logger.debug(f"Updated state for {task_config.name}: next due {next_due}")

    def _calculate_next_due(
        self, result: TaskResult, task_config: TaskConfig
    ) -> datetime | None:
        """Calculate the next due date based on the result and task configuration.

        Args:
            result: The result of the task execution, which includes status and skip reason.
            task_config: The configuration of the task, which includes frequency.
        """
        # Skipped or failed tasks should not update next due date
        match result.status:
            # Storing the current next due for skipped or failed task
            case TaskStatus.SKIPPED:
                # Disabled tasks have no next due date
                if result.skip_reason == SkipReason.DISABLED:
                    next_due = None
                else:
                    next_due = self.state.get_task_state(task_config.name).next_due
            case TaskStatus.FAILURE:
                next_due = self.state.get_task_state(task_config.name).next_due
            case _:
                # Calculating next due date for successful execution
                next_due = datetime.now() + timedelta(days=task_config.frequency)
        return next_due
