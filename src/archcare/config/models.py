"""
Configuration models for archcare using Pydantic.

These models provide type-safe configuration with validation.
"""

from datetime import datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class TaskType(Enum):
    AUTOMATED = "automated"
    MANUAL = "manual"


class TaskStatus(Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    SKIPPED = "skipped"
    RUNNING = "running"


class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class TaskConfig(BaseModel):
    """Configuration for a single maintenance task."""

    name: str = Field(..., description="Unique task identifier")
    task_type: TaskType = Field(
        ..., alias="type",
        description="Whether task runs automatically or requires manual trigger"
    )
    frequency: int = Field(
        ..., gt=0, description="Number of days between task executions"
    )
    description: str = Field(..., description="Human-readable task description")
    command: str = Field(..., description="Task command/identifier to execute")
    enabled: bool = Field(default=True, description="Whether task is enabled")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Ensure task name is valid identifier."""
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError(
                f"Task name must be alphanumeric with hyphens/underscores: {v}"
            )
        return v

    @field_validator("command")
    @classmethod
    def validate_command(cls, v: str) -> str:
        """Ensure command is a valid identifier."""
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError(
                f"Command must be alphanumeric with hyphens/underscores: {v}"
            )
        return v


class TasksConfig(BaseModel):
    """Collection of all task configurations."""

    tasks: dict[str, TaskConfig] = Field(
        default_factory=dict, description="Map of task name to task configuration"
    )

    def get_enabled_tasks(self) -> dict[str, TaskConfig]:
        """Return only enabled tasks."""
        return {name: task for name, task in self.tasks.items() if task.enabled}

    def get_tasks_by_type(self, task_type: TaskType) -> dict[str, TaskConfig]:
        """Return tasks filtered by type."""
        return {
            name: task
            for name, task in self.tasks.items()
            if task.task_type == task_type and task.enabled
        }

    def get_task(self, name: str) -> TaskConfig | None:
        """Get a specific task by name."""
        return self.tasks.get(name)


class IgnoredServicesConfig(BaseModel):
    """Configuration for services to ignore in failed-services check."""

    services: list[str] = Field(
        default_factory=list, description="List of systemd service names to ignore"
    )

    def is_ignored(self, service_name: str) -> bool:
        """Check if a service should be ignored."""
        return service_name in self.services


class CacheCleanupMapping(BaseModel):
    """Configuration for cache cleanup mappings."""

    path: str = Field(..., description="Cache directory path (supports ~)")
    max_age_days: int | None = Field(
        None,
        ge=0,
        description="Delete files older than this many days (None = don't delete by age)",
    )
    max_size_mb: int | None = Field(
        None, ge=0, description="Keep only this much data in MB (None = no size limit)"
    )
    pattern: str | None = Field(
        None, description="Glob pattern for files to clean (None = all files)"
    )

    @field_validator("path")
    @classmethod
    def expand_path(cls, v: str) -> str:
        """Expand ~ and environment variables in path."""
        return str(Path(v).expanduser())


class CacheCleanupConfig(BaseModel):
    """Configuration for cache cleanup operations."""

    mappings: list[CacheCleanupMapping] = Field(
        default_factory=list,
        description="List of cache directories and their cleanup rules",
    )


class AppSettings(BaseModel):
    """Application-wide settings."""

    # Paths
    log_dir: Path = Field(
        default=Path.home() / ".local/state/archcare/logs",
        description="Directory for log files",
    )
    state_file: Path = Field(
        default=Path.home() / ".local/state/archcare/state.json",
        description="File to track task execution state",
    )
    config_dir: Path = Field(
        default=Path.home() / ".config/archcare", description="Configuration directory"
    )

    # Logging
    log_retention_days: int = Field(
        default=30, ge=1, description="Number of days to keep log files"
    )
    log_level: LogLevel = Field(default=LogLevel.INFO, description="Logging level")

    # Behavior
    require_confirmation: bool = Field(
        default=True, description="Require user confirmation for destructive operations"
    )
    dry_run: bool = Field(
        default=False, description="Simulate operations without making changes"
    )

    @field_validator("log_dir", "state_file", "config_dir")
    @classmethod
    def expand_paths(cls, v: Path) -> Path:
        """Expand user home directory in paths."""
        return v.expanduser().resolve()

    def ensure_directories(self) -> None:
        """Create necessary directories if they don't exist."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)


class TaskState(BaseModel):
    """Runtime state for a task."""

    last_run: datetime | None = Field(None, description="Timestamp of last execution")
    last_status: TaskStatus | None = Field(None, description="Status of last execution")
    next_due: datetime | None = Field(None, description="When task should run next")
    run_count: int = Field(
        default=0, ge=0, description="Total number of times task has been executed"
    )
    last_error: str | None = Field(
        None, description="Error message from last failed run"
    )


class AppState(BaseModel):
    """Application state tracking task execution history."""

    tasks: dict[str, TaskState] = Field(
        default_factory=dict, description="Map of task name to task state"
    )
    last_updated: datetime = Field(
        default_factory=datetime.now, description="Last time state was updated"
    )

    def get_task_state(self, task_name: str) -> TaskState:
        """Get state for a task, creating if it doesn't exist."""
        if task_name not in self.tasks:
            self.tasks[task_name] = TaskState()  # type: ignore[call-arg]
        return self.tasks[task_name]

    def update_task_state(
        self,
        task_name: str,
        status: TaskStatus,
        next_due: datetime | None = None,
        error: str | None = None,
    ) -> None:
        """Update state after task execution."""
        state = self.get_task_state(task_name)
        state.last_run = datetime.now()
        state.last_status = status
        state.next_due = next_due
        state.run_count += 1
        state.last_error = error
        self.last_updated = datetime.now()
