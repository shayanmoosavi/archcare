"""
Core functionality for archcare task execution.
"""

from .models import (
    IssueSeverity,
    MaintenanceCheckResult,
    MaintenanceIssue,
    TaskResult,
    TaskStep,
    failed,
    partial,
    skipped,
    success,
)
from .scheduler import TaskScheduleInfo, TaskScheduler
from .task_registry import TaskDescriptor, TaskRegistry

__all__ = [
    # Models
    "IssueSeverity",
    "MaintenanceCheckResult",
    "MaintenanceIssue",
    "TaskResult",
    "TaskStep",
    "failed",
    "partial",
    "skipped",
    "success",
    # Scheduler
    "TaskScheduler",
    "TaskScheduleInfo",
    # Task registry
    "TaskRegistry",
    "TaskDescriptor",
]
