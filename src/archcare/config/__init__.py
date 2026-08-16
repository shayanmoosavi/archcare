"""
Configuration module for archcare.

Provides configuration loading, validation, and management.
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
