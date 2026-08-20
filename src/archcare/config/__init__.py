"""
Configuration and logging initialization package for Archcare.

Handles the loading, parsing, validation, and writing of TOML configuration
and JSON state files, as well as setting up the global logging environment.

Modules:
    defaults: Default TOML template builders for setting up fresh configurations.
    loader: Handles reading and writing TOML/JSON configuration and state files.
    logging: Sets up global and task-specific Loguru logger handlers.
    models: Pydantic configuration and state schemas and enums.

Public API:
    - [AppSettings][]: Application-wide settings model (log level, retention, etc.).
    - [AppState][]: Complete runtime state tracking last run and next due times.
    - [ConfigLoader][]: Core manager for loading and saving tasks, settings, state,
        and ignored services.
    - [IgnoredServicesConfig][]: Schema containing excluded systemd unit lists.
    - [LogLevel][]: Enum representing the supported loguru log levels.
    - [SkipReason][]: Enum representing reasons a scheduled task was skipped.
    - [TaskConfig][]: Model representing a specific task's configuration details.
    - [TasksConfig][]: Container mapping all defined tasks under `tasks.toml`.
    - [TaskState][]: Runtime state specifically tracked for an individual task.
    - [TaskStatus][]: Enum representing the completion status of a task run.
    - [TaskType][]: Enum specifying if a task is "automated" or "manual".
    - [create_default_config_files][]: Utility function to bootstrap config files
        for a new installation.
    - [setup_logging][]: Function to set up the main file/console loguru handlers.
    - [setup_task_logging][]: Function to set up distinct filtered log handlers for a running task.

See Also:
    - [archcare.config.loader][]: Complete ConfigLoader file management implementation
    - [archcare.config.logging][]: Complete Logging environment configuration
    - [archcare.config.models][]: Pydantic schemas and enums definitions
"""

from .loader import ConfigLoader, create_default_config_files
from .logging import setup_logging, setup_task_logging
from .models import (
    AppSettings,
    AppState,
    IgnoredServicesConfig,
    LogLevel,
    SkipReason,
    TaskConfig,
    TasksConfig,
    TaskState,
    TaskStatus,
    TaskType,
)

__all__ = [
    # Models
    "AppSettings",
    "AppState",
    "SkipReason",
    "TaskConfig",
    "TasksConfig",
    "TaskState",
    "TaskStatus",
    "TaskType",
    "LogLevel",
    "IgnoredServicesConfig",
    # Loader
    "ConfigLoader",
    "create_default_config_files",
    # Logging
    "setup_logging",
    "setup_task_logging",
]
