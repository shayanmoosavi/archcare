"""
Optional collaborator bundle for task execution.

See Also:
    - [`BaseTask`][archcare.core.base_task.BaseTask]: Consumes the bundle per task instance.
    - [`TaskExecutor`][archcare.core.executor.TaskExecutor]: Owns the shared bundle and derives
        task-facing bundles from it.
"""

from dataclasses import dataclass, field

from .interaction import NonInteractive, TaskInteraction
from .notifications import NotificationManager
from .progress import NoOpProgress, TaskProgress


@dataclass(frozen=True)
class TaskDependencies:
    """
    Optional behavioral collaborators injected into the executor and [`BaseTask`][].

    Data (config, settings, state) travels as explicit constructor arguments; collaborators travel
    in this bundle. Ports get null-object default factories, so an omitted field means "use the
    default implementation". `notification_manager` is the only None-able field: `None` means no
    notifier was supplied. `BaseTask` treats that as notifications disabled; it's resolved lazily
    upon first access at
    [`TaskExecutor.notification_manager`][archcare.core.executor.TaskExecutor.notification_manager].

    Attributes:
        interaction (TaskInteraction): User interaction port for confirmations. Defaults to
            [`NonInteractive`][].
        progress (TaskProgress): Real-time progress reporter. Defaults to [`NoOpProgress`][].
        notification_manager (NotificationManager | None): Desktop notification
            manager. Defaults to `None`.
    """

    interaction: TaskInteraction = field(default_factory=NonInteractive)
    progress: TaskProgress = field(default_factory=NoOpProgress)
    notification_manager: NotificationManager | None = None
