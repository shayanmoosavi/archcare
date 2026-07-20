"""
Core functionality for archcare task execution.
"""

from .models import (
    IssueSeverity,
    MaintenanceCheckDetails,
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
from .task_details import (
    FailedServiceInfo,
    FailedServicesDetails,
    HealthCheckDetails,
    HealthCheckSummary,
    MirrorlistUpdateDetails,
)
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
    # Task details
    "FailedServiceInfo",
    "FailedServicesDetails",
    "HealthCheckDetails",
    "HealthCheckSummary",
    "MaintenanceCheckDetails",
    "MirrorlistUpdateDetails",
    # Task registry
    "TaskRegistry",
    "TaskDescriptor",
]
