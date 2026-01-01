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
    "TaskConfig",
    "TasksConfig",
    "TaskState",
    "TaskStatus",
    "TaskType",
    "IgnoredServicesConfig",
    "CacheCleanupConfig",
    "CacheCleanupMapping",
    # Loader
    "ConfigLoader",
    "create_default_config_files",
]
