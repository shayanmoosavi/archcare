"""
Presenter layer for Archcare.

Terminal rendering for the CLI: presenters translate service-layer response DTOs into Rich-based
output, and task detail formatters render per-task domain details for verbose run output. This layer
is the CLI-side implementation of the
[TaskDetailFormatter][archcare.core.formatter.TaskDetailFormatter] port; a GUI frontend would supply
its own implementations and reuse `core/`, `config/`, and `services/` unmodified.

Modules:
    debug_presenter: Presenter for the `debug` command group.
    formatters: Implementation of task detail formatters.
    maintenance_presenter: Custom presenter for the `maintenance-check` task.
    setup_presenter: Presenter for the `setup` command group.
    task_presenter: Presenter for the `task` command group.

Public API:
    - [TaskPresenter][archcare.cli.presenters.task_presenter.TaskPresenter]:
        rendering for the `task` command group (run/status/list)
    - [SetupPresenter][archcare.cli.presenters.setup_presenter.SetupPresenter]:
        rendering for the `setup` command group (config/timers)
    - [DebugPresenter][archcare.cli.presenters.debug_presenter.DebugPresenter]:
        rendering for the `debug` command group
    - Formatters (one per task, implementing the detail formatter port):
        [FailedServicesFormatter][], [HealthCheckFormatter][], [MaintenanceCheckFormatter][],
        [MirrorlistUpdateFormatter][]

See Also:
    - [archcare.core.formatter][]: The port implemented by the formatters
"""

from .debug_presenter import DebugPresenter
from .formatters import (
    FailedServicesFormatter,
    HealthCheckFormatter,
    MaintenanceCheckFormatter,
    MirrorlistUpdateFormatter,
)
from .setup_presenter import SetupPresenter
from .task_presenter import TaskPresenter

__all__ = [
    # Presenters
    "TaskPresenter",
    "SetupPresenter",
    "DebugPresenter",
    # Formatters
    "FailedServicesFormatter",
    "HealthCheckFormatter",
    "MaintenanceCheckFormatter",
    "MirrorlistUpdateFormatter",
]
