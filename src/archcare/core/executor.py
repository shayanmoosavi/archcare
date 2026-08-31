"""
Task execution coordinator for the Archcare core layer.

This module provides [TaskExecutor][], which coordinates task instantiation, controls execution
lifecycles, and manages dynamic execution updates over persistent status states. It interfaces with
configuration loader, scheduler, task registry, and various ports (for user interactions, progress
tracking, and notifications).

Key Concepts:
    - **Execution Control**: It orchestrates loading task configurations, checking prerequisites
        (such as whether tasks are currently due or disabled), prompting for interactive approvals,
        running task routines, and tracking duration metrics.
    - **State Updates**: Post execution (regardless of whether a task succeeds, fails, or
        is skipped), it automatically re-calculates next-due recurrence intervals, updates
        system status maps, saves changes to disk, and corrects file permissions.

See Also:
    - [TaskScheduler][]: Checks task schedule timelines.
    - [TaskRegistry][]: Name-to-class mapping consumed here.
    - [BaseTask][]: Abstract interface for task classes.
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
    UserContext,
)

from .base_task import BaseTask
from .interaction import NonInteractive, TaskInteraction
from .models import TaskResult, skipped
from .notifications import NotificationManager
from .progress import NoOpProgress, TaskProgress
from .scheduler import TaskScheduler
from .task_registry import TaskRegistry


class TaskExecutor:
    """
    Coordinates task execution and state management.

    Handles resolving task metadata, instantiating task execution objects, executing
    pre-run filters (e.g., verifying if a task is enabled or due), launching lifecycle
    runs, and persisting execution results back to the state database.

    Attributes:
        config_loader (ConfigLoader): Handles reading and writing TOML configurations and
            JSON state.
        settings (AppSettings): Application-wide settings model.
        state (AppState): Tracking container of historical task run statistics.
        task_registry (TaskRegistry): Map linking task names to executing and
            detail formatter classes.
        user_context (UserContext): Resolves the active user context via
            `ARCHCARE_USER` environment variable.

    Methods:
        notification_manager: *(property)* The lazy-loaded shared desktop notification manager.
        execute_task: Execute a single task by name.

    Examples:
        Let's demonstrate how to construct a `TaskExecutor` using mocked dependencies:

        >>> from pathlib import Path
        >>> from archcare.config import AppSettings, AppState, ConfigLoader, UserContext
        >>> from archcare.core.task_registry import TaskRegistry
        >>> from archcare.core.executor import TaskExecutor
        >>>
        >>> # Construct mock dependencies
        >>> settings = AppSettings()
        >>> state = AppState(tasks={})
        >>> registry = TaskRegistry(())
        >>> loader = ConfigLoader()
        >>>
        >>> executor = TaskExecutor(
        ...     config_loader=loader,
        ...     settings=settings,
        ...     state=state,
        ...     task_registry=registry,
        ... )
        >>> executor.task_registry is registry
        True

    See Also:
        - [BaseTask][]: Base task implementation structure.
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
        progress: TaskProgress | None = None,
    ):
        """
        Initialize the task executor.

        Args:
            config_loader (ConfigLoader): ConfigLoader instance for reading and writing files.
            settings (AppSettings): Application settings.
            state (AppState): Application state for tracking execution history.
            task_registry (TaskRegistry): Static registry of task names mapped to their classes.
            interaction (TaskInteraction | None): User notification and confirmation adapter.
                Defaults to [NonInteractive][].
            notification_manager (NotificationManager | None): Desktop notifications sender.
                If `None`, it is lazily constructed on first access.
            user_context (UserContext | None): System user context resolution. If `None`, eagerly
                retrieved from active environment variables.
            progress (TaskProgress | None): Visual progress tracking adapter.
                Defaults to [NoOpProgress][].
        """
        self.config_loader = config_loader
        self.settings = settings
        self.state = state
        self.task_registry = task_registry
        self.user_context = user_context or UserContext.from_env()
        self._interaction = interaction or NonInteractive()
        self._progress = progress or NoOpProgress()
        self.__notification_manager = notification_manager

    @property
    def notification_manager(self) -> NotificationManager:
        """
        Retrieve or lazily construct the application notification manager.

        Returns:
            NotificationManager: Active notification sender.
        """
        if self.__notification_manager is None:
            self.__notification_manager = NotificationManager()
        return self.__notification_manager

    def _create_task(self, task_config: TaskConfig) -> BaseTask:
        """
        Create a task instance from its configuration.

        Looks up the concrete task class in `TaskRegistry` and wires it with
        the executor's shared settings, notification manager, and progress port.

        Args:
            task_config (TaskConfig): Configuration detail model of the task to construct.

        Returns:
            BaseTask: The instantiated task execution object.

        Raises:
            TaskNotRegisteredError: If the task name is not found in the static registry.
        """
        task_class = self.task_registry.get_task_class(task_config.name)

        return task_class(
            config=task_config,
            settings=self.settings,
            notification_manager=self.notification_manager,
            progress=self._progress,
        )

    def execute_task(self, task_name: str, force: bool = False) -> TaskResult:
        """
        Execute a single system maintenance task by name.

        Orchestrates loading active configurations, filtering task requirements (e.g. if the
        task is disabled or is not due, unless bypassed via `force`), initializing the task logger
        and progress bar, running pre-execution / execution / post-execution / rollback lifecycles,
        updating execution timestamps, and persisting states.

        Args:
            task_name (str): The unique string name of the target task.
            force (bool): Bypasses 'is_due' and 'enabled' checks to force running the task.
                Defaults to `False`.

        Returns:
            TaskResult: The results returned from the task run.

        Raises:
            UnknownTaskError: If the specified task cannot be loaded from configurations.
        """
        # Load task configuration
        tasks_config = self.config_loader.load_tasks()
        task_config = tasks_config.get_task(task_name)

        is_systemd = not self.user_context.is_interactive
        if not force:
            handle_disabled_result = self._handle_disabled_task(task_name, task_config, is_systemd)
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
        """
        Evaluate and handle execution attempts for disabled tasks.

        If the task is disabled:
        - In headless environments (such as systemd timers), it automatically halts and returns
            a skipped result status.
        - In interactive environments, it prompts the user to ask if they want to override the
            disable status and proceed anyway.

        Args:
            task_name (str): Name of the task under review.
            task_config (TaskConfig): Configuration details of the task.
            is_systemd (bool): `True` if the command is running as part of an unattended systemd
                timer session. Defaults to `False`.

        Returns:
            TaskResult | None: A skipped `TaskResult` if the execution was aborted/skipped,
                or `None` if the task is enabled or the user decided to override and run.
        """

        if not task_config.enabled:
            self._interaction.notify(
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
                    task.create_result(skipped("Cancelled by user", SkipReason.USER_CANCELLED))
                    if not self._interaction.confirm("Run anyway?")
                    else None
                )
        else:
            return None

    def _handle_due_task(
        self, task_name: str, tasks_config: TasksConfig, is_systemd: bool = False
    ) -> TaskResult | None:
        """
        Evaluate and handle execution attempts for tasks that are not yet due.

        If the task recurrence timeline has not expired:
        - In headless environments (such as systemd timers), it automatically halts and returns
            a skipped result status.
        - In interactive environments, it notifies the user and prompts to ask if they want to
            override and execute anyway.

        Args:
            task_name (str): Name of the task under review.
            tasks_config (TasksConfig): Collection of all task configurations.
            is_systemd (bool): `True` if running unattended. Defaults to `False`.

        Returns:
            TaskResult | None: A skipped `TaskResult` if the run was aborted, or `None` if the task
                is due or the user wants to execute anyway.
        """
        scheduler = TaskScheduler(tasks_config, self.state)
        task_schedule_info = scheduler.get_schedule_info(task_name)
        is_due = task_schedule_info.is_due
        reason = task_schedule_info.reason
        task_config = tasks_config.get_task(task_name)

        if not is_due:
            self._interaction.notify(f"Task is not due: {reason}")
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
                    if not self._interaction.confirm("Run anyway?")
                    else None
                )
        else:
            return None

    def _update_state(self, task_config: TaskConfig, result: TaskResult):
        """
        Update the task execution history and persist changes to the state file.

        Updates the app state tracking dictionary, saves JSON changes back to disk, and
        ensures the target file has correct user permissions if running under root sudo timers.

        Args:
            task_config (TaskConfig): Configuration of the executed task.
            result (TaskResult): The outcome of the execution attempt.
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

    def _calculate_next_due(self, result: TaskResult, task_config: TaskConfig) -> datetime | None:
        """
        Calculate the next due timestamp based on task configuration and execution result.

        Success statuses cause the scheduler to shift the next due date by the task's recurrence
        frequency days. Skipped or failed tasks preserve their existing next-due dates, unless the
        task was skipped due to a permanent disable configuration (which removes scheduled
        timelines entirely).

        Args:
            result (TaskResult): The execution outcome model containing status and skip details.
            task_config (TaskConfig): Configuration containing the interval days frequency.

        Returns:
            datetime | None: The calculated next due timestamp, or `None` if the task has been
                permanently disabled.
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
