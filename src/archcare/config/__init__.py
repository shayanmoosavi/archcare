"""
Configuration module for archcare.

Provides configuration loading, validation, and management.
"""

from .loader import ConfigLoader, create_default_config_files
from .models import (
    AppSettings,
    AppState,
    CacheCleanupConfig,
    CacheCleanupMapping,
    IgnoredServicesConfig,
    SkipReason,
    TaskConfig,
    TasksConfig,
    TaskState,
    TaskStatus,
    TaskType,
    LogLevel,
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
    "CacheCleanupConfig",
    "CacheCleanupMapping",
    # Loader
    "ConfigLoader",
    "create_default_config_files",
]
