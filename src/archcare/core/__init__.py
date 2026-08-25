"""
Core functionality for Archcare task execution.

This package is the frontend-agnostic engine of Archcare: it defines the task lifecycle
([BaseTask][]), the orchestration and state-tracking machinery
([TaskExecutor][archcare.core.executor.TaskExecutor]), due-date evaluation ([TaskScheduler][]),
and the typed result/detail contracts shared between tasks and their presenters.

The core layer never imports from `cli/` or `services/`. Environment-specific behavior is isolated
behind duck-typed ports — the [TaskInteraction][archcare.core.interaction.TaskInteraction],
[TaskProgress][archcare.core.progress.TaskProgress], and
[TaskDetailFormatter][archcare.core.formatter.TaskDetailFormatter] protocols —
so a future GUI can reuse this package unmodified by supplying its own
implementations.

Key Concepts:
    - **Task lifecycle**: every task implements [BaseTask][], whose `run()`
      drives `pre_check()` -> `should_run()` -> `execute()` -> `post_execute()`
      (with rollback support).
    - **Typed results**: [TaskResult][] is generic over per-task detail
      dataclasses ([FailedServicesDetails][], [HealthCheckDetails][], etc.), so
      results carry structured data end to end instead of loose dicts.
    - **Static registry**: [TaskRegistry][] maps each task name to its execution
      class and detail formatter class.

Modules:
    base_task: Abstract [BaseTask][] contract and execution lifecycle.
    executor: [TaskExecutor][archcare.core.executor.TaskExecutor]
        orchestrating instantiation, guards, and state updates.
    exceptions: Core-layer exception hierarchy rooted at `ArchcareCoreError`.
    formatter: [TaskDetailFormatter][archcare.core.formatter.TaskDetailFormatter]
        port for rendering task details.
    interaction: [TaskInteraction][archcare.core.interaction.TaskInteraction]
        port for confirm/notify during runs.
    models: [TaskResult][], step/severity types, and result factory functions.
    notifications: Desktop notification delivery via `notify-send`.
    progress: [TaskProgress][archcare.core.progress.TaskProgress] port plus
        no-op and Rich implementations.
    scheduler: [TaskScheduler][] evaluating due/overdue status from frequency and history.
    task_details: Per-task frozen detail dataclasses.
    task_registry: [TaskRegistry][] and [TaskDescriptor][] name-to-class mapping.

Public API:
    - [BaseTask][]: Abstract base every maintenance task inherits from.
    - [TaskResult][]: Generic run outcome carrying status, message, error, and details.
    - [success][]: Factory for successful results.
    - [failed][]: Factory for failed results.
    - [skipped][]: Factory for skipped results (with a
        [SkipReason][archcare.config.enums.SkipReason]).
    - [partial][]: Factory for partially-successful results.
    - [IssueSeverity][]: Severity classification for maintenance issues.
    - [MaintenanceIssue][]: Single issue reported by the maintenance-check task.
    - [TaskStep][]: Named milestone used for progress reporting.
    - [TaskScheduler][]: Computes due/overdue status from config and state.
    - [TaskScheduleInfo][]: Per-task schedule snapshot returned by the scheduler.
    - [FailedServiceInfo][]: Diagnostic details for one failed systemd unit.
    - [FailedServicesDetails][]: Details payload of the failed-services task.
    - [HealthCheckDetails][]: Details payload of the health-check task.
    - [HealthCheckSummary][]: Aggregated health metrics snapshot.
    - [MaintenanceCheckDetails][]: Details payload of the maintenance-check task.
    - [MaintenanceCheckSummary][]: Aggregated counts/message for maintenance issues.
    - [MirrorlistUpdateDetails][]: Details payload of the mirrorlist-update task.
    - [TaskRegistry][]: Static lookup of task name -> execution/formatter classes.
    - [TaskDescriptor][]: One registry entry binding a name to its classes.

See Also:
    - [archcare.config][]: Configuration/state schemas consumed by the executor.
    - [TaskExecutor][archcare.core.executor.TaskExecutor]: Primary consumer of this package's API.
"""

from .base_task import BaseTask
from .models import (
    IssueSeverity,
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
    MaintenanceCheckDetails,
    MaintenanceCheckSummary,
    MirrorlistUpdateDetails,
)
from .task_registry import TaskDescriptor, TaskRegistry

__all__ = [
    # Base task
    "BaseTask",
    # Models
    "IssueSeverity",
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
    "MaintenanceCheckSummary",
    "MirrorlistUpdateDetails",
    # Task registry
    "TaskRegistry",
    "TaskDescriptor",
]
