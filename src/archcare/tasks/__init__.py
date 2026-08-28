"""
Task implementations for Archcare.

Concrete maintenance task classes that inherit from [BaseTask][archcare.core.base_task.BaseTask] and
implement the system maintenance operations exposed through the CLI. Each task produces a typed
[TaskResult][archcare.core.models.TaskResult] with a per-task details payload from
[archcare.core.task_details][].

This package is the *tasks* layer of the architecture: it orchestrates the `utils/` OS-boundary
helpers according to the workflow defined in `core/`, without depending on `cli/` or `services/`.
Registration happens exclusively in the static task registry (`cli/context.py`
`DEFAULT_TASK_REGISTRY`), not here.

Available tasks:

- `failed-services`: Detects failed systemd services, filters out ignored ones, and collects
    diagnostic details (status, recent journal logs).
- `health-check`: Runs system health checks — disk, memory, CPU, filesystem errors, pacman database,
    and package file integrity — and reports findings by severity.
- `mirrorlist-update`: Refreshes the pacman mirrorlist via `reflector` with automatic backup,
    validation, and rollback.
- `maintenance-check`: Scheduler-aware report of due/overdue tasks, failed automated tasks, and
    broken systemd timers, with notification and report-file support.

Public API:
    - [FailedServicesTask][]: Failed systemd service detection and diagnostics
    - [HealthCheckTask][]: Comprehensive system health checks
    - [MirrorlistUpdateTask][]: Reflector-based mirrorlist refresh with rollback
    - [MaintenanceCheckTask][]: Task schedule/overdue monitoring

See Also:
    - [BaseTask][archcare.core.base_task.BaseTask]: Abstract task contract and execution workflow
    - [archcare.core.task_details][]: Details dataclasses each task produces
"""

from .failed_services import FailedServicesTask
from .health_check import HealthCheckTask
from .maintenance_check import MaintenanceCheckTask
from .mirrorlist_update import MirrorlistUpdateTask

__all__ = [
    "FailedServicesTask",
    "HealthCheckTask",
    "MirrorlistUpdateTask",
    "MaintenanceCheckTask",
]
