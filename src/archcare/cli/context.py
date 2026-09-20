"""
Application context for the Archcare CLI.

Defines [`AppContext`][] — the per-invocation object built once by the root Typer callback and
threaded through every command via `ctx.obj`. It lazily constructs the [`ConfigLoader`][],
[`AppSettings`][], and [`TaskExecutor`][] (wiring in the CLI-side
[`TaskInteraction`][archcare.core.interaction.TaskInteraction] and
[`TaskProgress`][archcare.core.progress.TaskProgress] implementations only when
running interactively), so nothing reaches for global state.

Also defines `DEFAULT_TASK_REGISTRY` — the single, static [`TaskRegistry`][] mapping every task name
to its execution class and CLI detail formatter. This is the one place new tasks must be registered.

See Also:
    - [`archcare.cli.app`][]: Root callback constructing the context
    - [`archcare.cli.commands`][]: Commands using the context
    - [`UserContext`][archcare.config.user.UserContext]: Resolves the active user and interactivity,
        threaded into the context at construction
"""

from dataclasses import dataclass, field

from archcare.cli.interaction import CliInteraction
from archcare.cli.presenters import (
    FailedServicesFormatter,
    HealthCheckFormatter,
    MaintenanceCheckFormatter,
    MirrorlistUpdateFormatter,
)
from archcare.cli.progress import RichProgress
from archcare.config import AppSettings, ConfigLoader, UserContext, setup_logging
from archcare.core import TaskDescriptor, TaskRegistry
from archcare.core.executor import TaskExecutor
from archcare.services.exceptions import ConfigNotInitializedError
from archcare.tasks import (
    FailedServicesTask,
    HealthCheckTask,
    MaintenanceCheckTask,
    MirrorlistUpdateTask,
)

DEFAULT_TASK_REGISTRY = TaskRegistry(
    # Register every archcare task here: name -> (task class, CLI formatter class).
    # This is the single source of truth for task name -> execution/formatting routing.
    (
        TaskDescriptor("failed-services", FailedServicesTask, FailedServicesFormatter),
        TaskDescriptor("health-check", HealthCheckTask, HealthCheckFormatter),
        TaskDescriptor("mirrorlist-update", MirrorlistUpdateTask, MirrorlistUpdateFormatter),
        TaskDescriptor("maintenance-check", MaintenanceCheckTask, MaintenanceCheckFormatter),
    )
)


@dataclass
class AppContext:
    """
    Per-invocation context, built once by the root callback and read by
    every command via `ctx.obj`.

    Wraps the user's [`UserContext`][] together with lazy handles to the config loader, settings,
    and [`TaskExecutor`][] so commands don't have to construct any of them manually. Also exposes a
    [`UserContext.is_interactive`][] proxy (`is_interactive`) and the static `task_registry` for
    cheap read-only access.

    Args:
        devel (bool): Whether `--devel` was passed; controls console log verbosity.
        user_ctx (UserContext): User context for this invocation (resolves active user
            and interactivity).

    Raises:
        ConfigNotInitializedError: Raised by `setup_logging` when `tasks.toml` doesn't exist yet
            (i.e., the user hasn't run `archcare setup config`).
    """

    devel: bool
    user_ctx: UserContext

    _loader: ConfigLoader | None = field(default=None, init=False, repr=False)
    _settings: AppSettings | None = field(default=None, init=False, repr=False)
    _executor: TaskExecutor | None = field(default=None, init=False, repr=False)

    @property
    def is_interactive(self) -> bool:
        """
        Whether the invocation is interactive (user terminal vs. systemd timer).

        Proxied from [`UserContext.is_interactive`][]; used here to decide whether to wire in
        interactive [`TaskInteraction`][archcare.core.interaction.TaskInteraction] and
        [`TaskProgress`][archcare.core.progress.TaskProgress] adapters.

        Returns:
            bool: `True` for an interactive invocation.
        """
        return self.user_ctx.is_interactive

    @property
    def __loader(self) -> ConfigLoader:
        """
        Lazily construct the cached [`ConfigLoader`][].

        *(private)* This property is an implementation detail and not intended to be accessed from
        outside the class.

        Returns:
            ConfigLoader: The shared loader for this invocation, bound to the archcare user
                from [`UserContext`][].
        """
        if self._loader is None:
            self._loader = ConfigLoader(user=self.user_ctx.archcare_user)
        return self._loader

    @property
    def settings(self) -> AppSettings:
        """
        Lazily load and cache the application settings.

        Returns:
            AppSettings: Settings read from `settings.toml` via the cached [`ConfigLoader`][].
        """
        if self._settings is None:
            settings = self.__loader.load_settings()
            self._settings = settings
        return self._settings

    @property
    def task_registry(self) -> TaskRegistry:
        """
        Static task registry.

        Returns:
            TaskRegistry: The module-level `DEFAULT_TASK_REGISTRY` (see in source code).

        See also:
            [`archcare.cli.commands.task`][]: The consumer of this property
        """
        return DEFAULT_TASK_REGISTRY

    @property
    def executor(self) -> TaskExecutor:
        """
        Lazily construct the cached [`TaskExecutor`][].

        Wires in the CLI-side [`TaskInteraction`][archcare.core.interaction.TaskInteraction]
        ([`CliInteraction`][]) and [`TaskProgress`][archcare.core.progress.TaskProgress]
        ([`RichProgress`][]) implementations only when running interactively; non-interactive
        (systemd) runs leave them as `None` so the executor falls back to its non-interactive
        defaults.

        Returns:
            TaskExecutor: The shared executor for this invocation.
        """
        if self._executor is None:
            state = self.__loader.load_state()
            executor = TaskExecutor(
                config_loader=self.__loader,
                settings=self.settings,
                state=state,
                task_registry=self.task_registry,
                interaction=CliInteraction() if self.is_interactive else None,
                user_context=self.user_ctx,
                progress=RichProgress() if self.is_interactive else None,
            )
            self._executor = executor
        return self._executor

    def setup_logging(self, user: str | None = None) -> None:
        """
        Configure logging for this context.

        Validates that `tasks.toml` exists (raising [`ConfigNotInitializedError`][] otherwise),
        bootstraps directories, installs the default logging configuration, then re-applies it
        (via `reconfigure=True`) if the user's settings differ from defaults in any of:
        log directory, level, or retention. Refreshes the cached loader and settings using the
        resolved user.

        Args:
            user (str | None): Target archcare user; when `None`, uses `user_ctx.archcare_user`.
                Used by [`executor_for_user`][] to target a different user than the one the context
                was built for.

        Raises:
            ConfigNotInitializedError: If `tasks.toml` doesn't exist in the default config
                directory.
        """
        default_settings = AppSettings(user=self.user_ctx.archcare_user)
        tasks_file_exists = (default_settings.config_dir / "tasks.toml").exists()
        if not tasks_file_exists:
            raise ConfigNotInitializedError()

        default_settings.ensure_directories()
        setup_logging(default_settings, devel_mode=self.devel)

        self._loader = ConfigLoader(user=user or self.user_ctx.archcare_user)
        self._settings = self.__loader.load_settings()

        # Reconfigure logging only if the user's settings differ from defaults
        if (
            self.settings.log_dir != default_settings.log_dir
            or self.settings.log_level != default_settings.log_level
            or self.settings.log_retention_days != default_settings.log_retention_days
        ):
            setup_logging(self.settings, reconfigure=True, devel_mode=self.devel)

    def executor_for_user(self, user: str) -> TaskExecutor:
        """
        Build a fresh, uncached [`TaskExecutor`][] scoped to a specific user.

        Used by `setup timers`, which must read the target (`SUDO_USER`) user's config rather than
        this context's own user — `SUDO_USER` and `ARCHCARE_USER` are unrelated env vars, and
        `setup timers` always runs interactively via `sudo`, never via the `ARCHCARE_USER`
        systemd path. The returned executor is **not** cached on `self`; it exists only for
        the caller.

        Args:
            user (str): Target archcare user (from `SUDO_USER`).

        Returns:
            TaskExecutor: A fresh executor bound to the target user's config and state.

        See also:
            [`TimerService`][archcare.services.setup_service.TimerService]: The class that uses
                the returned executor

        Note:
            `user_context` is deliberately omitted: this executor never calls `execute_task()`
            (`TimerService` only reads `config_loader`/`state` off it), and `ARCHCARE_USER` is
                always unset in this sudo-driven flow anyway.
        """
        self.setup_logging(user)
        state = self.__loader.load_state()

        # user_context deliberately omitted: this executor never calls
        # execute_task() (TimerService only reads config_loader/state off
        # it), and ARCHCARE_USER is always unset in this sudo-driven flow
        # anyway
        executor = TaskExecutor(
            config_loader=self.__loader,
            settings=self.settings,
            state=state,
            task_registry=self.task_registry,
        )
        return executor
