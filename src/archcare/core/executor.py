"""
Task executor for archcare.

This module provides [TaskExecutor][], the orchestration engine that turns a task
name plus configuration into a fully executed, state-tracked run. It sits at the
center of the core layer and glues together:

- Configuration lookup and due/disabled evaluation ([TaskScheduler][])
- Task instantiation via the static [TaskRegistry][]
- The unified execution lifecycle defined by [BaseTask][]
- Persistence of run outcomes ([AppState][]) including next-due scheduling

Execution Lifecycle:
    1. Resolve the task's [TaskConfig][] from the tasks configuration.
    2. Unless forced, apply the disabled/not-due guards: disabled tasks and
       not-yet-due tasks may short-circuit into a skipped result (unattended
       contexts) or prompt the user for confirmation through the injected
       [TaskInteraction][] port.
    3. Instantiate the concrete task class from the registry and delegate to
       its `run()` method.
    4. Persist the resulting status and recalculated next-due date back to
       `state.json`, chowning the state file when running as root.

The executor never renders output itself: presentation belongs to the caller,
and environment-specific behavior flows exclusively through injected ports
([TaskInteraction][], [TaskProgress][]), keeping this layer frontend-agnostic.

See Also:
    - [TaskScheduler][]: Due-date evaluation used by the guards.
    - [TaskRegistry][]: Name-to-class mapping consumed here.
    - [BaseTask][]: The task contract coordinated by this class.
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

    The executor is the single entry point the frontend (CLI today, a future
    GUI tomorrow) uses to run maintenance tasks. It:

    - Instantiates tasks from their configuration via [TaskRegistry][]
    - Guards execution against disabled tasks and not-yet-due schedules,
      delegating any user prompting to the [TaskInteraction][] port
    - Manages the task lifecycle by delegating to [BaseTask.run][]
    - Updates and persists task state after every outcome, recalculating
      next-due dates so schedules never silently drift

    Dependency injection throughout: nothing here reaches for global state.
    Interactive behavior is opt-in — when no interaction/progress ports are
    supplied, non-interactive defaults are used, making the executor safe for
    systemd timers and tests.

    Attributes:
        config_loader (ConfigLoader): Loader for TOML tasks/settings and JSON
            state persistence.
        settings (AppSettings): Application-wide settings threaded into every
            created task.
        state (AppState): Application state tracking runs; mutated after each
            execution and persisted via `config_loader.save_state()`.
        task_registry (TaskRegistry): Static registry of task name -> execution
            class (and detail formatter for the presentation layer). Built once
            at the top of the CLI (or a future GUI) and passed in — the
            executor never mutates it.
        user_context (UserContext): Resolves `ARCHCARE_USER` semantics; used to
            detect unattended systemd runs and to chown state files as root.

    Methods:
        notification_manager: *(property)* The lazy-loaded shared desktop notification manager.
        execute_task: Execute a single task by name.

    Examples:
        >>> from unittest.mock import MagicMock
        >>> from archcare.core.executor import TaskExecutor
        >>> from archcare.core.task_registry import TaskRegistry
        >>> registry = TaskRegistry(())
        >>> executor = TaskExecutor(
        ...     config_loader=MagicMock(),
        ...     settings=MagicMock(),
        ...     state=MagicMock(),
        ...     task_registry=registry,
        ... )
        >>> executor.task_registry is registry
        True

    See Also:
        - [TaskScheduler][]: Evaluates due status for the guards.
        - [AppContext][archcare.cli.context.AppContext]: Builds an executor per CLI invocation.
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
        Initialize task executor.

        Args:
            config_loader (ConfigLoader): Loader for configurations and state.
            settings (AppSettings): Application settings.
            state (AppState): Application state (for tracking runs).
            task_registry (TaskRegistry): Static registry of task name -> execution class
                (and detail formatter for the presentation layer). Built once at the
                top of the CLI (or a future GUI) and passed in - `TaskExecutor` never
                mutates it.
            interaction (TaskInteraction | None): Port for user notifications/confirmations
                during execution (e.g. "task is disabled, run anyway?"). Defaults to
                `NonInteractive`, which never confirms - safe for systemd and tests.
            notification_manager (NotificationManager | None): Desktop notification sender,
                threaded down to every task it creates. Lazily constructed on first access
                if not provided, since `NotificationManager.__init__()` does a real
                `notify-send` availability check.
            user_context (UserContext | None): Resolves `ARCHCARE_USER` once per invocation.
                Unlike `notification_manager`, this is cheap (just an env read), so it's
                constructed eagerly from the environment if not provided.
            progress (TaskProgress | None): Port for progress tracking. Defaults to
                `NoOpProgress`, which does nothing.
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
        Return the shared desktop notification manager, constructing it lazily.

        `NotificationManager.__init__()` performs a real `notify-send`
        availability check, so construction is deferred until first access —
        and skipped entirely when a manager was injected via `__init__()`.

        Returns:
            NotificationManager: Manager threaded down into every created task.
        """
        if self.__notification_manager is None:
            self.__notification_manager = NotificationManager()
        return self.__notification_manager

    def _create_task(self, task_config: TaskConfig) -> BaseTask:
        """
        Create a task instance from its configuration.

        Looks up the concrete task class in [TaskRegistry][] and wires it with
        the executor's shared settings, notification manager, and progress port.

        Args:
            task_config (TaskConfig): Task configuration supplying the name to
                look up and the per-task settings.

        Returns:
            BaseTask: Instantiated, ready-to-run task object.

        Raises:
            TaskNotRegisteredError: If task name is not registered
                (propagated from [TaskRegistry.get_task_class][]).
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
        Execute a single task by name.

        Loads the task's configuration, applies the disabled/not-due guards (unless `force` is set),
        runs the task through its full [BaseTask.run][] lifecycle, and persists the outcome to state
        — all or nothing: by the time this returns, [AppState][] always reflects the run (including
        skips).

        Args:
            task_name (str): Name of the task to execute (must exist in `tasks.toml`).
            force (bool): Whether to force running the task, bypassing the
                disabled and due-date guards. Defaults to False.

        Returns:
            TaskResult: Result from task execution, including skipped results
                produced by the guards.

        Raises:
            UnknownTaskError: If task is not defined in the tasks configuration
                (propagated from [TasksConfig.get_task][]).

        Examples:
            >>> from unittest.mock import MagicMock
            >>> from archcare.config import TasksConfig, TaskConfig, TaskType
            >>> from archcare.core.executor import TaskExecutor
            >>> from archcare.core.task_registry import TaskRegistry
            >>> tasks_config = TasksConfig(tasks={
            ...     "health-check": TaskConfig(
            ...         name="health-check",
            ...         type=TaskType.AUTOMATED,
            ...         frequency=7,
            ...         description="System health",
            ...         enabled=True,
            ...     )
            ... })
            >>> loader = MagicMock()
            >>> loader.load_tasks.return_value = tasks_config
            >>> executor = TaskExecutor(
            ...     config_loader=loader,
            ...     settings=MagicMock(),
            ...     state=MagicMock(),
            ...     task_registry=TaskRegistry(()),
            ... )

            Unknown task names fail immediately:

            >>> executor.execute_task("nope")
            Traceback (most recent call last):
                ...
            archcare.config.exceptions.UnknownTaskError: Task not found: nope

            Names defined in config still require a registered class:

            >>> _ = executor.execute_task(  # doctest: +NORMALIZE_WHITESPACE
            ...     "health-check", force=True
            ... )
            Traceback (most recent call last):
                ...
            archcare.core.exceptions.TaskNotRegisteredError: No task registered for: 'health-check'.
                Available tasks: []
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
        Guard against executing a disabled task.

        When `task_config.enabled` is false, resolves the run into either a
        skip or an explicit decision to proceed:

        - Unattended contexts (`is_systemd`) always produce a `SKIPPED` result
          with reason `DISABLED` — prompts cannot be answered without a user.
        - Interactive contexts notify the user and ask "Run anyway?":
          declining returns `USER_CANCELLED`, accepting returns `None` so
          execution continues.

        Skipped results carry a start time (via `task.set_start_time()`) so
        duration metrics remain meaningful for cancelled runs.

        Args:
            task_name (str): Name of the task being guarded (used in notifications).
            task_config (TaskConfig): Resolved configuration; only `enabled` is
                consulted.
            is_systemd (bool): True when running unattended (non-interactive
                user context). Defaults to False.

        Returns:
            TaskResult | None: A skipped result if the run must short-circuit,
                or `None` if execution may proceed.

        See Also:
            [TaskExecutor.execute_task][]: Caller that persists the returned skip.
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
        Guard against executing a task that is not yet due.

        Evaluates the task's schedule via [TaskScheduler][] and, when the task
        is not due:

        - Unattended contexts (`is_systemd`) return a `NOT_DUE` skip result —
          there is no user available to override the schedule.
        - Interactive contexts notify the user of the schedule reason
          (e.g. "Due in 3 days") and ask whether to run anyway: declining
          returns `USER_CANCELLED`, accepting returns `None` so execution proceeds
          despite the schedule.

        Args:
            task_name (str): Name of the task being evaluated.
            tasks_config (TasksConfig): Complete task configuration collection,
                handed to the scheduler.
            is_systemd (bool): True when running unattended. Defaults to False.

        Returns:
            TaskResult | None: A skipped result if the run must not proceed,
                otherwise None.

        See Also:
            [TaskScheduler.get_schedule_info][]: Source of the due/reason evaluation.
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

    def _update_state(self, task_config: TaskConfig, result: TaskResult) -> None:
        """
        Update task state after execution.

        Centralizes all state bookkeeping so every exit path of
        [TaskExecutor.execute_task][] (success, failure, skip) records a
        consistent history:

        1. Compute the next due timestamp via `_calculate_next_due()`.
        2. Merge status/error/skip-reason into the shared [AppState][].
        3. Save state to disk through the config loader.
        4. Chown the state file (and its directory) to the target user when
           running as root under systemd, keeping the state file owned by the
           invoking user rather than root.

        Args:
            task_config (TaskConfig): Configuration of executed task (name and
                frequency).
            result (TaskResult): Result from task execution.
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
        Calculate the next due date based on the result and task configuration.

        Policy by outcome:

        - SUCCESS (or any non-skip/failure status): now + frequency days — a
          completed run restarts the schedule.
        - FAILURE: preserve the previously scheduled next due date, so a failed
          run doesn't push maintenance further out.
        - SKIPPED with SkipReason.DISABLED: clear next due entirely (a disabled
          task has no schedule).
        - Other skips (not due, user cancelled): preserve the existing schedule.

        Args:
            result (TaskResult): The result of the task execution, which includes
                status and skip reason.
            task_config (TaskConfig): The configuration of the task, which
                includes frequency (in days).

        Returns:
            datetime | None: The next due timestamp for the task, the preserved
                prior value, or None when the task is disabled.
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
