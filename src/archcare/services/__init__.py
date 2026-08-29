"""
Services layer - high-level business operations for the view layer (CLI/GUI).

This package provides the facade between the view layer and the core/config layers. Each service
owns one command group, validates inputs, delegates to core machinery
([TaskExecutor][archcare.core.executor.TaskExecutor],
[TaskScheduler][archcare.core.scheduler.TaskScheduler],
[NotificationManager][archcare.core.notifications.NotificationManager]), and returns response DTOs
from [archcare.services.responses][] so presenters never touch raw business state.

Modules:
    debug_service: Business logic for the `debug` command group.
    exceptions: Domain execptions for services layer.
    responses: Response DTOs returned by the services layer.
    setup_service: Business logic for `setup config` and `setup timers`.
    task_service: Task service for handling task related operations.

Public API:
    - [TaskService][archcare.services.task_service.TaskService]:
        `task` command group — run tasks, list tasks, schedule status.
    - [ConfigService][archcare.services.setup_service.ConfigService]:
        `setup config` — default configuration file creation.
    - [TimerService][archcare.services.setup_service.TimerService]:
        `setup timers` — systemd template unit installation and timer enabling.
    - [DebugService][archcare.services.debug_service.DebugService]:
        `debug` command group — notification testing.
    - [resolve_systemd_target_user][archcare.services.setup_service.resolve_systemd_target_user]:
        Helper resolving the non-root user for systemd units.

Exceptions raised by this layer are defined in
[archcare.services.exceptions][archcare.services.exceptions], all rooted in
[ArchcareError][archcare.exceptions.ArchcareError].

Layering rule: this package may import from `core/` and `config/` but never
from `cli/` (which is the only layer allowed to depend on services).

See Also:
    - [archcare.services.responses][]: Response DTOs returned by all services
    - [archcare.services.exceptions][]: Service-layer exception hierarchy
"""

from .debug_service import DebugService
from .setup_service import ConfigService, TimerService, resolve_systemd_target_user
from .task_service import TaskService

__all__ = [
    "TaskService",
    "ConfigService",
    "TimerService",
    "DebugService",
    "resolve_systemd_target_user",
]
