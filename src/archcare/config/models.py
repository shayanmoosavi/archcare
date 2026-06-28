"""
Configuration models for archcare using Pydantic.

These models provide type-safe configuration with validation.
"""

from datetime import datetime
from enum import Enum
from os import getenv
from pathlib import Path
from typing import Self

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator


class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class TaskType(Enum):
    AUTOMATED = "automated"
    MANUAL = "manual"

    def __str__(self):
        return self.value


class TaskStatus(Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    SKIPPED = "skipped"
    PARTIAL = "partial"

    def __str__(self) -> str:
        return self.value


class SkipReason(Enum):
    """Reasons why a task was skipped."""

    NO_WORK_NEEDED = (
        "no_work_needed"  # Task found nothing to do (e.g., no failed services)
    )
    DISABLED = "disabled"  # Task is disabled in configuration
    DEPENDENCY_FAILED = "dependency_failed"  # Required dependency not available
    USER_CANCELLED = "user_cancelled"  # User chose not to run the task
    NOT_DUE = "not_due"  # Task executed but not due yet
    OTHER = "other"  # Other reason (with custom message)

    def __str__(self) -> str:
        return self.value


class TaskConfig(BaseModel):
    """Configuration for a single maintenance task."""

    name: str = Field(..., description="Unique task identifier")
    task_type: TaskType = Field(
        ...,
        alias="type",
        description="Whether task runs automatically or requires manual trigger",
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

    def get_tasks_by_type(self, task_type: str) -> dict[str, TaskConfig]:
        """Return tasks filtered by type."""
        if task_type not in ["automated", "manual"]:
            raise ValueError("task_type must be 'automated' or 'manual'")
        return {
            name: task
            for name, task in self.tasks.items()
            if str(task.task_type) == task_type and task.enabled
        }

    def get_task(self, name: str) -> TaskConfig:
        """Get a specific task by name."""
        task_name = self.tasks.get(name)
        if not task_name:
            raise ValueError(f"Task not found: {name}")
        return task_name


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


class MirrorlistSettings(BaseModel):
    """Settings for mirrorlist update task."""

    path: Path = Field(
        default=Path("/etc/pacman.d/mirrorlist"),
        description="Path to store the mirrorlists",
    )
    country: str | list[str] = Field(
        default="Germany", description="Country for mirror selection"
    )
    protocol: str = Field(
        default="https", description="Protocol to use (http/https/rsync)"
    )
    sort: str = Field(
        default="rate", description="The criteria to sort the mirrors with"
    )
    latest: int = Field(
        default=20,
        ge=1,
        le=50,
        description="The number of most recently synchronized mirrors",
    )
    number_of_mirrors: int = Field(
        default=5, ge=1, le=50, description="Number of mirrors to include"
    )

    @field_validator("protocol")
    @classmethod
    def validate_protocol(cls, v: str) -> str:
        """Validate protocol value."""
        if v not in ["http", "https", "rsync"]:
            raise ValueError("protocol must be 'http', 'https', or 'rsync'")
        return v

    @field_validator("sort")
    @classmethod
    def validate_sort(cls, v: str) -> str:
        """Validate sort value."""
        valid_sorts = ["age", "rate", "country", "score", "delay"]
        if v not in valid_sorts:
            raise ValueError(f"sort must be one of {valid_sorts}")
        return v


class MaintenanceCheckSettings(BaseModel):
    """Settings for maintenance check task."""

    critical_threshold_days: int = Field(
        default=7, ge=0, description="Days overdue before task is considered critical"
    )
    warning_threshold_days: int = Field(
        default=0, ge=0, description="Days overdue before task is considered warning"
    )
    output_mode: str = Field(
        default="terminal", description="Output mode: 'terminal', 'file', or 'both'"
    )
    show_notifications: bool = Field(
        default=True, description="Show desktop notifications"
    )
    notification_level: str = Field(
        default="warning",
        description="Minimum severity for notifications: 'critical', 'warning', 'info'",
    )
    report_retention_days: int = Field(
        default=30, ge=1, description="Days to keep maintenance check reports"
    )
    require_acknowledgment: bool = Field(
        default=True, description="Require user acknowledgment for critical issues"
    )

    @field_validator("output_mode")
    @classmethod
    def validate_output_mode(cls, v: str) -> str:
        """Validate output mode value."""
        valid_modes = ["terminal", "file", "both"]
        if v not in valid_modes:
            raise ValueError(f"output_mode must be one of: {', '.join(valid_modes)}")
        return v

    @field_validator("notification_level")
    @classmethod
    def validate_notification_level(cls, v: str) -> str:
        """Validate notification level value."""
        valid_levels = ["critical", "warning", "info"]
        if v not in valid_levels:
            raise ValueError(
                f"notification_level must be one of: {', '.join(valid_levels)}"
            )
        return v


class AppSettings(BaseModel):
    """Application-wide settings."""

    # Global settings
    # This corresponds to the global section in the settings.toml file

    # Username
    user: str | None = None

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

    # mirrorlist-specific settings
    # This corresponds to the [mirrorlist] section in the settings.toml file
    mirrorlist: MirrorlistSettings = Field(
        default_factory=MirrorlistSettings,
        description="Settings for mirrorlist update task",
    )

    # maintenance check specific settings
    # This corresponds to the [maintenance_check] section in the settings.toml file
    maintenance_check: MaintenanceCheckSettings = Field(
        default_factory=MaintenanceCheckSettings,
        description="Settings for maintenance check task",
    )

    # Paths
    @computed_field  # type: ignore[prop-decorator]
    @property
    def home_dir(self) -> Path:
        """Home directory of the user."""
        # Handle sudo case: if running with sudo, use SUDO_USER's home instead of root's
        sudo_user = getenv("SUDO_USER")
        if sudo_user:
            return Path(f"/home/{sudo_user}")
        return Path(f"/home/{self.user}") if self.user else Path.home()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def log_dir(self) -> Path:
        """Directory for log files."""
        return self.home_dir / ".local/state/archcare/logs"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def state_file(self) -> Path:
        """File to track task execution state."""
        return self.home_dir / ".local/state/archcare/state.json"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def config_dir(self) -> Path:
        """Configuration directory."""
        return self.home_dir / ".config/archcare"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def report_dir(self) -> Path:
        """Directory for maintenance check reports."""
        return self.home_dir / ".local/state/archcare/reports"

    @classmethod
    def expand_paths(cls, v: Path) -> Path:
        """Expand user home directory in paths."""
        return v.expanduser().resolve()

    @model_validator(mode="after")
    def validate_paths(self) -> Self:
        paths: list[Path] = [
            self.log_dir,
            self.state_file,
            self.config_dir,
            self.report_dir,
        ]

        if not all(self.expand_paths(path) for path in paths):
            raise ValueError("All paths must be valid and accessible.")

        return self

    def ensure_directories(self) -> None:
        """Create necessary directories if they don't exist."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)


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
    skip_reason: SkipReason | None = Field(
        None, description="Reason why task was skipped"
    )
    skip_message: str | None = Field(
        None, description="Additional context for skip reason"
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
        skip_reason: SkipReason | None = None,
        skip_message: str | None = None,
    ) -> None:
        """Update state after task execution."""
        state = self.get_task_state(task_name)
        state.last_run = datetime.now()
        state.last_status = status
        state.next_due = next_due
        state.run_count += 1
        state.last_error = error
        state.skip_reason = skip_reason
        state.skip_message = skip_message
        self.last_updated = datetime.now()
