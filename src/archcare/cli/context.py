"""Application context for the Archcare CLI."""

from dataclasses import dataclass, field

from archcare.cli.interaction import CliInteraction
from archcare.config import AppSettings, ConfigLoader
from archcare.core.executor import TaskExecutor
from archcare.services.exceptions import ConfigNotInitializedError
from archcare.tasks import (
    BaseTask,
    FailedServicesTask,
    HealthCheckTask,
    MaintenanceCheckTask,
    MirrorlistUpdateTask,
)
from archcare.utils import UserContext
from archcare.utils.logging import setup_logging

_TASK_REGISTRY: dict[str, type[BaseTask]] = {
    "failed-services": FailedServicesTask,
    "check-health": HealthCheckTask,
    "update-mirrorlist": MirrorlistUpdateTask,
    "check-maintenance": MaintenanceCheckTask,
}


def _register_tasks(executor: TaskExecutor) -> None:
    for command, task_class in _TASK_REGISTRY.items():
        executor.register_task(command, task_class)


@dataclass
class AppContext:
    """
    Per-invocation context, built once by the root callback and read by
    every command via `ctx.obj`.

    Args:
        devel: Whether --devel was passed; controls console log verbosity.
        user_ctx: UserContext object for this invocation.
    """

    devel: bool
    user_ctx: UserContext

    _loader: ConfigLoader | None = field(default=None, init=False, repr=False)
    _settings: AppSettings | None = field(default=None, init=False, repr=False)
    _executor: TaskExecutor | None = field(default=None, init=False, repr=False)

    @property
    def is_interactive(self) -> bool:
        return self.user_ctx.is_interactive

    @property
    def __loader(self) -> ConfigLoader:
        if self._loader is None:
            self._loader = ConfigLoader(user=self.user_ctx.archcare_user)
        return self._loader

    @property
    def settings(self) -> AppSettings:
        if self._settings is None:
            settings = self.__loader.load_settings()
            self._settings = settings
        return self._settings

    @property
    def executor(self) -> TaskExecutor:
        if self._executor is None:
            state = self.__loader.load_state()
            executor = TaskExecutor(
                config_loader=self.__loader,
                settings=self.settings,
                state=state,
                interaction=CliInteraction() if self.is_interactive else None,
                user_context=self.user_ctx,
            )
            _register_tasks(executor)
            self._executor = executor
        return self._executor

    def setup_logging(self, user: str | None = None) -> None:
        """Setup logging for this context."""

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
        Build a fresh, uncached TaskExecutor scoped to a specific user.

        Used by `setup timers`, which must read the target (SUDO_USER)
        user's config rather than this context's own user - SUDO_USER and
        ARCHCARE_USER are unrelated env vars and `setup timers` always runs
        interactively via sudo, never via the ARCHCARE_USER systemd path.
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
        )
        _register_tasks(executor)
        return executor
