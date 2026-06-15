"""Response data transfer objects (DTOs) returned by the Archcare service layer."""

from dataclasses import dataclass
from pathlib import Path

from archcare.config import TaskConfig
from archcare.core.models import TaskResult
from archcare.core.scheduler import TaskScheduleInfo


@dataclass
class TaskRunResponse:
    """Outcome of running a single task."""

    task_name: str
    outcome: TaskResult
    is_interactive: bool


@dataclass
class TaskListResponse:
    """Tasks matching an optional type filter."""

    tasks: dict[str, TaskConfig]
    filtered_by: str | None


@dataclass
class TaskStatusResponse:
    """Schedule information for one or all tasks."""

    schedule_info: list[TaskScheduleInfo]
    summary: dict | None = None
    due_only: bool = False


@dataclass
class ConfigInitResponse:
    """Outcome of initializing default configuration files."""

    config_dir: Path


@dataclass
class InstallTemplatesResponse:
    """Outcome of installing systemd timer templates."""

    service_file: Path
    timer_file: Path
    dry_run: bool


@dataclass
class ReloadSystemdResponse:
    """Outcome of reloading the systemd daemon."""

    success: bool


@dataclass
class EnableTimersResponse:
    """Outcome of enabling systemd timers for automated tasks."""

    enabled_timers: list[str]
    failed_timers: list[str]
    timer_status_output: str | None


@dataclass
class NotificationTestResponse:
    """Outcome of sending a test desktop notification."""

    severity: str
    title: str
