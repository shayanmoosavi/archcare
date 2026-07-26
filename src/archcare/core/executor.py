"""
Task executor for archcare.

Handles task instantiation and execution coordination.
"""

from datetime import datetime, timedelta

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
from archcare.tasks import BaseTask
from archcare.utils import UserContext
from archcare.utils.notifications import NotificationManager

from .interaction import NonInteractive, TaskInteraction
from .models import TaskResult, skipped
from .scheduler import TaskScheduler
from .task_registry import TaskRegistry


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
        task_registry: TaskRegistry,
        interaction: TaskInteraction | None = None,
        notification_manager: NotificationManager | None = None,
        user_context: UserContext | None = None,
    ):
        """
        Initialize task executor.

        Args:
            config_loader: ConfigLoader for loading configurations
            settings: Application settings
            state: Application state (for tracking runs)
            task_registry: Static registry of task name -> execution class
             (and detail formatter for the presentation layer). Built
             once at the top of the CLI (or a future GUI) and passed
             in - TaskExecutor never mutates it.
            interaction: Port for user notifications/confirmations during execution
             (e.g. "task is disabled, run anyway?"). Defaults to NonInteractive,
            which never confirms - safe for systemd and tests.
            notification_manager: Desktop notification sender, threaded down
             to every task it creates. Lazily constructed on first access if
             not provided, since NotificationManager.__init__() does a real
             notify-send availability check.
            user_context: Resolves ARCHCARE_USER once per invocation. Unlike
            notification_manager, this is cheap (just an env read), so it's
            constructed eagerly from the environment if not provided.
        """
        self.config_loader = config_loader
        self.settings = settings
        self.state = state
        self.task_registry = task_registry
        self.interaction = interaction or NonInteractive()
        self._notification_manager = notification_manager
        self.user_context = user_context or UserContext.from_env()

    @property
    def notification_manager(self) -> NotificationManager:
        if self._notification_manager is None:
            self._notification_manager = NotificationManager()
        return self._notification_manager

    def _create_task(self, task_config: TaskConfig) -> BaseTask:
        """
        Create a task instance from its configuration.

        Args:
            task_config: Task configuration

        Returns:
            Instantiated task object

        Raises:
            TaskNotRegisteredError: If task name is not registered
                (propagated from TaskRegistry.get_task_class()).
        """
        task_class = self.task_registry.get_task_class(task_config.name)

        return task_class(
            config=task_config,
            settings=self.settings,
            notification_manager=self.notification_manager,
        )

    def execute_task(self, task_name: str, force: bool = False) -> TaskResult:
        """
        Execute a single task by name.

        Args:
            task_name: Name of the task to execute
            force: Whether to force running the task. It skips

        Returns:
            TaskResult from task execution

        Raises:
            UnknownTaskError: If task is not found (propagated from
                TasksConfig.get_task()).
        """
        # Load task configuration
        tasks_config = self.config_loader.load_tasks()
        task_config = tasks_config.get_task(task_name)

        is_systemd = not self.user_context.is_interactive
        if not force:
            handle_disabled_result = self._handle_disabled_task(
                task_name, task_config, is_systemd
            )
            if handle_disabled_result:
                self._update_state(task_config, handle_disabled_result)
                return handle_disabled_result

            handle_due_result = self._handle_due_task(task_name, tasks_config, is_systemd)
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
            error=result.error,
            skip_reason=result.skip_reason,
        )

        # Save state to disk
        self.config_loader.save_state(self.state)

        # Change ownership if running as root via systemd
        state_file = self.settings.state_file
        self.user_context.chown_if_root(state_file, state_file.parent)

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
