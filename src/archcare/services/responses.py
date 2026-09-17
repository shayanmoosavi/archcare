"""
Response data transfer objects (DTOs) returned by the Archcare service layer.

These frozen-in-practice dataclasses are the contract between [`archcare.services`][] (business
logic) and [`archcare.cli`][] (presentation). Service methods build and return these responses; CLI
presenters consume them and render terminal output. Keeping presentation concerns out of the
services layer preserves the ability to swap in a GUI frontend that consumes the same DTOs.

Response families:

- **Task operations** ([`TaskRunResponse`][], [`TaskListResponse`][], [`TaskStatusResponse`][]):
    returned by `TaskService` for running, listing, and checking task schedules.
- **Setup operations** ([`ConfigInitResponse`][], [`InstallTemplatesResponse`][],
    [`ReloadSystemdResponse`][], [`TimerEnableResponse`][], [`TimerSetupResponse`][]): returned by
    [`ConfigService`][archcare.services.setup_service.ConfigService] and
    [`TimerService`][archcare.services.setup_service.TimerService] for configuration creation and
    systemd timer installation.
- **Debug operations** ([`NotificationTestResponse`][]): returned by `DebugService` for
    notification testing.

See Also:
    - [`TaskService`][archcare.services.task_service.TaskService]: Producer of
        task-operation responses
    - [`archcare.services.setup_service`][]: Producers of setup-operation responses
    - [`DebugService`][archcare.services.debug_service]: Producer of debug-operation responses
"""

from dataclasses import dataclass
from pathlib import Path

from archcare.config import TaskConfig
from archcare.core import TaskResult, TaskScheduleInfo


@dataclass
class TaskRunResponse:
    """
    Outcome of running a single task.

    Attributes:
        task_name (str): Name of the task that was executed.
        outcome (TaskResult): The full execution result (status, message, typed details, timing)
            produced by the task.
        is_interactive (bool): Whether the invocation is interactive — i.e., run by a user in a
            terminal rather than non-interactively via a systemd timer. Presenters use it to choose
            rich vs. quiet output formatting.

    See also:
        - [`run_task`][archcare.services.task_service.TaskService.run_task]: Producer
            of this response
        - [`render_run`][archcare.cli.presenters.task_presenter.TaskPresenter.render_run]: Consumer
            of this response
    """

    task_name: str
    outcome: TaskResult
    is_interactive: bool


@dataclass
class TaskListResponse:
    """
    Tasks matching an optional type filter.

    Attributes:
        tasks (dict[str, TaskConfig]): Matching tasks keyed by task name, in
            the order defined in `tasks.toml`.
        filtered_by (str | None): The task-type filter that was applied
            (`"automated"`, `"manual"`), or `None` when unfiltered.

    See also:
        - [`list_tasks`][archcare.services.task_service.TaskService.list_tasks]: Producer of
            this response
        - [`render_list`][archcare.cli.presenters.task_presenter.TaskPresenter.render_list]:
            Consumer of this response
    """

    tasks: dict[str, TaskConfig]
    filtered_by: str | None


@dataclass
class TaskStatusResponse:
    """
    Schedule information for one or all tasks.

    Attributes:
        schedule_info (list[TaskScheduleInfo]): Per-task schedule details (last run, next due,
            days overdue) from the scheduler.
        summary (dict[str, int] | None): Aggregate maintenance counts by category (as computed by
            [`TaskScheduler.get_maintenance_summary`][archcare.core.scheduler.TaskScheduler.get_maintenance_summary]),
            or `None` when a single task was queried.
        due_only (bool): Whether the query was restricted to due tasks (`--due` flag), which
            suppresses not-yet-due entries.

    See also:
        - [`get_task_status`][archcare.services.task_service.TaskService.get_task_status]: Producer
            of this response
        - [`render_status`][archcare.cli.presenters.task_presenter.TaskPresenter.render_status]:
            Consumer of this response
    """

    schedule_info: list[TaskScheduleInfo]
    summary: dict[str, int] | None = None
    due_only: bool = False


@dataclass
class ConfigInitResponse:
    """
    Outcome of initializing default configuration files.

    Attributes:
        config_dir (Path): Directory the configuration files were written to
            (typically `~/.config/archcare/`).
        created_files (list[Path]): Files that were newly created by this run.
        skipped_files (list[Path]): Files that already existed and were left
            untouched to preserve user customizations.

    See also:
        - [`initialize`][archcare.services.setup_service.ConfigService.initialize]: Producer of
            this response
        - [`SetupPresenter`][archcare.cli.presenters.setup_presenter.SetupPresenter]: Consumer of
            this response (`render_config_init()`)
    """

    config_dir: Path
    created_files: list[Path]
    skipped_files: list[Path]


@dataclass
class InstallTemplatesResponse:
    """
    Outcome of installing systemd timer templates.

    Attributes:
        service_file (Path): Path of the installed `archcare@.service` unit.
        timer_file (Path): Path of the installed `archcare@.timer` unit.
        dry_run (bool): `True` when only the planned paths were reported without writing any files.

    See also:
        - [`install_templates`][archcare.services.setup_service.TimerService.install_templates]:
            Producer of this response
        - [`SetupPresenter`][archcare.cli.presenters.setup_presenter.SetupPresenter]: Consumer of
            this response (`render_template_installation()`)
    """

    service_file: Path
    timer_file: Path
    dry_run: bool


@dataclass
class ReloadSystemdResponse:
    """
    Outcome of reloading the systemd daemon.

    Attributes:
        dry_run (bool): `True` when `systemctl daemon-reload` was skipped and only reported.

    See also:
        - [`reload`][archcare.services.setup_service.TimerService.reload]: Producer of
            this response
        - [`SetupPresenter`][archcare.cli.presenters.setup_presenter.SetupPresenter]: Consumer of
            this response (`render_systemd_reload()`)
    """

    dry_run: bool


@dataclass
class TimerEnableResponse:
    """
    Outcome of `systemctl enable --now` for a single timer.

    Used by [`TimerService.setup_timers`][archcare.services.setup_service.TimerService.setup_timers]
    to aggregate the results of each individual installed systemd timer.

    Attributes:
        timer_name (str): Name of the timer unit that was enabled
            (e.g., `"archcare@health-check.timer"`).
        enabled (bool): Whether the enable-and-start operation succeeded.

    See also:
        [`TimerSetupResponse`][]: The aggregator of this response
    """

    timer_name: str
    enabled: bool


@dataclass
class TimerSetupResponse:
    """
    Outcome of the timer-enabling step of `setup timers`.

    `enabled_timers` and `timer_status` are empty/`None` unless timers were actually enabled (i.e.
    `enable=True` and `dry_run=False`).

    Attributes:
        automated_tasks (dict[str, TaskConfig]): The automated tasks that timers were (or would be)
            set up for, keyed by task name.
        enabled_timers (list[TimerEnableResponse]): Per-timer enable results; empty when enabling
            was skipped or performed as a dry run.
        timer_status (str | None): Human-readable status of the enable step, or `None` when timers
            were not enabled.

    See also:
        - [`setup_timers`][archcare.services.setup_service.TimerService.setup_timers]: Producer of
            this response
        - [`SetupPresenter`][archcare.cli.presenters.setup_presenter.SetupPresenter]: Consumer of
            this response (`render_timer_setup()`)
    """

    automated_tasks: dict[str, TaskConfig]
    enabled_timers: list[TimerEnableResponse]
    timer_status: str | None


@dataclass
class NotificationTestResponse:
    """
    Outcome of sending a test desktop notification.

    Attributes:
        severity (str): Severity level the test notification was sent with (e.g., `"warning"`).
        title (str): Title text of the notification that was sent.

    See also:
        - [`test_notification`][archcare.services.debug_service.DebugService.test_notification]:
            Producer of this response
        - [`DebugPresenter`][archcare.cli.presenters.debug_presenter.DebugPresenter]: Consumer of
            this response (`render_test_notification()`)
    """

    severity: str
    title: str
