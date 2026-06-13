"""Shared state and initialization for the Archcare CLI.

Holds the global executor singleton and the helpers that depend on it.
"""

import typer

from archcare.config import AppSettings, ConfigLoader, TasksConfig
from archcare.core import TaskExecutor
from archcare.tasks import (
    BaseTask,
    FailedServicesTask,
    HealthCheckTask,
    MaintenanceCheckTask,
    MirrorlistUpdateTask,
)
from archcare.utils.logging import setup_logging
from archcare.utils.output import print_error, print_info

_devel: bool = False
_loader: ConfigLoader | None = None
_settings: AppSettings | None = None
_executor: TaskExecutor | None = None


def get_executor(user: str | None = None) -> TaskExecutor:
    """
    Get or create the task executor.

    Returns:
        TaskExecutor instance
    """
    global _loader, _settings, _executor

    if not _executor:

        # Set up default logging first
        default_settings = AppSettings(user=user)
        default_settings.ensure_directories()
        setup_logging(default_settings, devel_mode=_devel)

        # Initialize configuration
        if not _loader:
            _loader = ConfigLoader(user=user)

        if not _settings:
            _settings = _loader.load_settings()

            # Reconfigure logging with user's custom settings if they differ
            # Check if any logging-related settings changed
            if (
                _settings.log_dir != default_settings.log_dir
                or _settings.log_level != default_settings.log_level
                or _settings.log_retention_days != default_settings.log_retention_days
            ):
                setup_logging(_settings, reconfigure=True, devel_mode=_devel)

        # Load state
        state = _loader.load_state()

        # Create executor
        _executor = TaskExecutor(
            config_loader=_loader,
            settings=_settings,
            state=state,
        )

        # Register all available tasks
        _register_tasks(_executor)

    return _executor


def _register_tasks(executor: TaskExecutor) -> None:
    """
    Register all available task implementations.

    Args:
        executor: TaskExecutor to register tasks with
    """
    tasks_mapping: dict[str, type[BaseTask]] = {
        "failed-services": FailedServicesTask,
        "check-health": HealthCheckTask,
        "update-mirrorlist": MirrorlistUpdateTask,
        "check-maintenance": MaintenanceCheckTask,
    }

    for command, task_class in tasks_mapping.items():
        executor.register_task(command, task_class)


def validate_task_name(task_name: str, tasks_config: TasksConfig):
    try:
        tasks_config.get_task(task_name)
    except ValueError:
        print_error(f"Task not found: {task_name}")
        print_info("Use 'archcare list' to see available tasks")
        raise typer.Exit(1)
