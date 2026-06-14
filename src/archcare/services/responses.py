"""Response data transfer objects (DTOs) returned by the Archcare service layer."""

from dataclasses import dataclass

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
