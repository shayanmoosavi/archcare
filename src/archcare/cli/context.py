"""Application context for the Archcare CLI."""

from dataclasses import dataclass, field

from archcare.cli.interaction import CliInteraction
from archcare.config import AppSettings, ConfigLoader
from archcare.core import TaskExecutor
from archcare.tasks import (
    BaseTask,
    FailedServicesTask,
    HealthCheckTask,
    MaintenanceCheckTask,
    MirrorlistUpdateTask,
)
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
        user: Username to run as, derived from the ARCHCARE_USER env var
              (set by systemd; absent means an interactive invocation).
    """

    devel: bool
    user: str | None

    _loader: ConfigLoader | None = field(default=None, init=False, repr=False)
    _settings: AppSettings | None = field(default=None, init=False, repr=False)
    _executor: TaskExecutor | None = field(default=None, init=False, repr=False)

    @property
    def is_interactive(self) -> bool:
        return self.user is None

    @property
    def settings(self) -> AppSettings:
        if self._settings is None:
            self._build_default()
        return self._settings  # pyright: ignore[reportReturnType]

    @property
    def executor(self) -> TaskExecutor:
        if self._executor is None:
            self._build_default()
        return self._executor  # pyright: ignore[reportReturnType]

    def _build_default(self) -> None:
        """Lazily build the executor/settings for this context's own user."""
        self._loader = ConfigLoader(user=self.user)

        default_settings = AppSettings(user=self.user)
        default_settings.ensure_directories()
        setup_logging(default_settings, devel_mode=self.devel)

        settings = self._loader.load_settings()

        # Reconfigure logging only if the user's settings differ from defaults
        if (
            settings.log_dir != default_settings.log_dir
            or settings.log_level != default_settings.log_level
            or settings.log_retention_days != default_settings.log_retention_days
        ):
            setup_logging(settings, reconfigure=True, devel_mode=self.devel)

        self._settings = settings
        state = self._loader.load_state()

        executor = TaskExecutor(
            config_loader=self._loader,
            settings=settings,
            state=state,
            interaction=CliInteraction(is_interactive=self.is_interactive),
        )
        _register_tasks(executor)
        self._executor = executor

    def executor_for_user(self, user: str) -> TaskExecutor:
        """
        Build a fresh, uncached TaskExecutor scoped to a specific user.

        Used by `setup timers`, which must read the target (SUDO_USER)
        user's config rather than this context's own user - SUDO_USER and
        ARCHCARE_USER are unrelated env vars and `setup timers` always runs
        interactively via sudo, never via the ARCHCARE_USER systemd path.
        """
        loader = ConfigLoader(user=user)
        settings = loader.load_settings()
        state = loader.load_state()

        executor = TaskExecutor(
            config_loader=loader,
            settings=settings,
            state=state,
        )
        _register_tasks(executor)
        return executor
