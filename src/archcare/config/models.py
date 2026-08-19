"""
Configuration models for Archcare using Pydantic

This module defines the data contracts for Archcare's configuration system, which is built
around three main concepts:

1. **Task Configuration** ([TaskConfig][TaskConfig], [TasksConfig][TasksConfig]):
    Defined in `tasks.toml`, specifies which maintenance tasks to run, their frequency,
    type (automated vs manual), and enabled state.

2. **Application Settings** ([AppSettings][AppSettings]): Defined in `settings.toml`,
    controls global behavior like logging, confirmations, and task-specific options
    (mirrorlist, maintenance check).

3. **Runtime State** ([TaskState][TaskState], [AppState][AppState]): Persisted in `state.json`,
    tracks task execution history (last run, next due, run count, errors) to
    enable scheduling decisions.

All models use Pydantic's validation framework to ensure type safety and provide clear error
messages on configuration errors.
"""

from datetime import datetime
from enum import Enum
from os import getenv
from pathlib import Path
from pwd import getpwnam
from typing import Self

from pydantic import (
    BaseModel,
    Field,
    computed_field,
    field_serializer,
    field_validator,
    model_validator,
)

from archcare.utils import is_valid_systemd_unit_name

from .exceptions import (
    HomeDirectoryResolutionError,
    InvalidTaskTypeFilterError,
    InvalidUnitNameError,
    UnknownTaskError,
)


class LogLevel(Enum):
    """
    Logging severity levels for Archcare operations

    Controls which log messages are written to log files. Higher severity levels
    include messages from lower levels (e.g., `ERROR` includes `ERROR` and `CRITICAL`).

    Configuration Examples:
        ```toml title="tasks.toml"
        log_level = "INFO"  # settings.toml: typical production setting
        log_level = "DEBUG" # settings.toml: troubleshooting mode
        ```
    """

    DEBUG = "DEBUG"
    """Detailed debugging info, variable values, function calls"""

    INFO = "INFO"
    """Normal operations ("Task started", "Mirror list updated")"""

    WARNING = "WARNING"
    """Non-critical issues ("Task overdue", "Old log files deleted")"""

    ERROR = "ERROR"
    """Task failures and exceptions (logged with full traceback)"""

    CRITICAL = "CRITICAL"
    """System-level failures that affect Archcare operation"""

    def __str__(self) -> str:
        return self.value


class TaskType(Enum):
    """
    Task execution modes for Archcare

    Examples:
        ```toml title="tasks.toml"
        [health-check]
        type = "automated"      # Runs on schedule automatically
        frequency = 7           # Every 7 days

        [mirrorlist-update]
        type = "manual"         # User must run explicitly
        frequency = 15          # User should run every 15 days
        ```
    """

    AUTOMATED = "automated"
    """
        - Executed automatically at scheduled intervals if no manual run is in progress
        - Example: health-check runs weekly without user intervention
        - Respects frequency setting; next_due is calculated from last_run + frequency days
    """

    MANUAL = "manual"
    """
        - Only executed when explicitly requested by the user (via CLI command)
        - Useful for potentially disruptive operations (mirror list updates, system upgrades)
        - frequency setting still defines how often it SHOULD run; skipped with `NOT_DUE` reason
        - User receives notifications when manual tasks are overdue
    """

    def __str__(self):
        return self.value


class TaskStatus(Enum):
    """
    Execution outcome for a completed task run

    State Persistence:
        `last_status` persists in `state.json` for reporting and scheduling decisions.
    """

    SUCCESS = "success"
    """
        - Task completed without errors; all work accomplished
        - Example: `health-check` found no issues, or `mirrorlist-update` succeeded
        - `next_due` is set for the next scheduled run
    """

    FAILURE = "failure"
    """
        - Task encountered a critical error; work incomplete
        - Example: no network connection, permission denied, or task raised exception
        - Error message stored in `last_error`; user should review logs
        - `next_due` is untouched; automated task will be retried on next
            scheduled run (systemd timer)
    """

    SKIPPED = "skipped"
    """
        - Task did not run; preserved for auditing (not counted in success/failure metrics)
        - Example: task is disabled, not due yet, or missing dependency
        - `skip_reason` explains why (`NO_WORK_NEEDED`, `DISABLED`, `NOT_DUE`, etc.)
        - Does not update `next_due`; scheduling unaffected
    """

    PARTIAL = "partial"
    """
        - Task ran with mixed results; some work completed, some failed
        - Example: `health-check` found warnings (e.g., low disk space) but no
            critical failures (e.g., package file integrity check failed)
        - Less critical than `FAILURE`; usually safe to retry
        - Details in `last_error`; `next_due` updated based on partial results
    """

    def __str__(self) -> str:
        return self.value


class SkipReason(Enum):
    """
    Reasons why a task execution was skipped

    Example State Progression:
        - initial state: skip_reason = None
        - after first success: skip_reason = None, next_due = now + 7 days
        - check before due: skip_reason = NOT_DUE, last_status = SKIPPED
        - on due date but task fails: skip_reason = None, last_status = FAILURE
    """

    NO_WORK_NEEDED = "no_work_needed"
    """
        - Task ran but found nothing to do
        - Example: `failed-services` found no failed services
        - Treated as a successful run; next_due still advances
        - Important for auditing: confirms task ran, not just disabled
    """

    DISABLED = "disabled"
    """
        - Task is disabled in configuration (enabled: false)
        - Example: user temporarily disabled `mirrorlist-update` in `tasks.toml`
        - Does not affect scheduling; when re-enabled, next_due continues from where
            it left off
    """

    DEPENDENCY_FAILED = "dependency_failed"
    """
        - Required system component or dependency not available
        - Example: reflector package is not installed for mirrorlist update
        - The missing dependency is reported to the user and logged; task cannot run
            until resolved
    """

    USER_CANCELLED = "user_cancelled"
    """
        - User chose not to run task when prompted
        - Example: user said "no" when asked whether to run an already executed task
        - Task treated as explicitly declined; next_due not advanced (task still "due")
        - Useful for manual tasks where user may need to run it later
    """

    NOT_DUE = "not_due"
    """
        - Task execution window hasn't elapsed yet
        - Example: `health-check` runs monthly; next execution in 3 days
        - Applies to both automated and manual tasks; prevents unnecessary runs
    """

    OTHER = "other"
    """
        - Miscellaneous reason; check `last_error` for custom message
        - Example: resource exhaustion, unexpected executor state, or custom task logic
        - Reserved for edge cases and future extensibility
    """

    def __str__(self) -> str:
        return self.value


class TaskConfig(BaseModel):
    """
    Configuration for a single maintenance task

    Defines how a task should behave: its name, execution type (automated vs manual),
    frequency, description, and enabled state. Aggregated by [TasksConfig][TasksConfig].

    Attributes:
        name (str): Unique identifier for the task (alphanumeric, hyphens, underscores)
              Used as dict key and in CLI commands; must be globally unique

              Examples: "health-check", "mirrorlist-update", "failed_services"

        task_type (TaskType): Controls execution mode (see TaskType enum)

            - `"automated"`: runs on schedule without user interaction
            - `"manual"`: only runs on explicit user command

        frequency (int): How often task should run, in days (must be > 0).
                   Defines `next_due` calculation: `last_run` + frequency days

        description (str): Human-readable purpose, shown in CLI output and logs
                    Example: "Check for due system maintenance tasks"

        enabled (bool): Whether task should execute; disabled tasks are skipped with
                        reason `DISABLED`. Useful for temporary configuration without deletion.

    Example Configuration:
        ```toml title="tasks.toml"
        [health-check]
        type = "automated"
        frequency = 7
        description = "Perform health checks on system components"
        enabled = true

        [mirrorlist-update]
        type = "manual"
        frequency = 15
        description = "Update pacman mirror list for optimal download speeds"
        enabled = true

        [maintenance-check]
        type = "automated"
        frequency = 30
        description = "Check for due system maintenance tasks"
        enabled = true
        ```

    Validation:
        - name must be alphanumeric (with hyphens/underscores only)
        - frequency must be > 0 (raises `ValueError` otherwise)
        - `task_type` serialized to string for TOML compatibility

    State Interaction:
        Paired with `TaskState` (same name key in `AppState.tasks`) to track
        execution history. A `TaskConfig` defines the policy; `TaskState` tracks
        actual runs (`last_run`, `last_status`, `next_due`).

    See also:
        - [TasksConfig][TasksConfig]: collection of all task configurations
        - [AppState][AppState]: runtime state including task execution history
        - [TaskState][TaskState]: per-task execution state (last run, next due, last status)
    """

    name: str = Field(..., description="Unique task identifier")
    task_type: TaskType = Field(
        ...,
        alias="type",
        description="Whether task runs automatically or requires manual trigger",
    )
    frequency: int = Field(..., gt=0, description="Number of days between task executions")
    description: str = Field(..., description="Human-readable task description")
    enabled: bool = Field(default=True, description="Whether task is enabled")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Ensure task name is valid."""
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError(f"Task name must be alphanumeric with hyphens/underscores: {v}")
        return v

    @field_serializer("task_type")
    def serialize_task_type(self, task_type: TaskType) -> str:
        """Serialize task_type to string for TOML compatibility."""
        return str(task_type)


class TasksConfig(BaseModel):
    """
    Collection of all task configurations

    Loaded from `tasks.toml` and serves as the task registry for the application.
    Provides query methods to filter tasks by type or enabled state, enabling
    orchestration logic (e.g., "run all enabled automated tasks").

    Attributes:
        tasks (dict[str, TaskConfig]): Dict mapping task names (str) to `TaskConfig` objects.
               Empty dict if no tasks defined (fallback for graceful failure)

    Methods:
        get_enabled_tasks: Get only enabled tasks.
        get_tasks_by_type: Get tasks filtered by type.
        get_task: Get a specific task by name.

    Examples:
        >>> from archcare.config.models import TasksConfig
        >>> tasks_config = TasksConfig(
        ...    tasks={
        ...        "health-check": TaskConfig(
        ...            name="health-check",
        ...            type=TaskType.AUTOMATED,
        ...            frequency=7,
        ...            description="...",
        ...            enabled=True
        ...        ),
        ...        "mirrorlist-update": TaskConfig(
        ...            name="mirrorlist-update",
        ...            type=TaskType.MANUAL,
        ...            frequency=15,
        ...            description="...",
        ...            enabled=True
        ...        ),
        ...    }
        ... )
        >>> print(tasks_config.tasks["health-check"].name)
        health-check
        >>> print(tasks_config.tasks["mirrorlist-update"].frequency)
        15
    """

    tasks: dict[str, TaskConfig] = Field(
        default_factory=dict, description="Map of task name to task configuration"
    )

    def get_enabled_tasks(self) -> dict[str, TaskConfig]:
        """
        Get only enabled tasks

        Return only tasks with `enabled=True`, filtered from all configured tasks.

        Returns:
            (dict[str, TaskConfig]): Mapping of task names to their configurations

        Examples:
            >>> from archcare.config.models import TasksConfig
            >>> tasks_config = TasksConfig(
            ...    tasks={
            ...        "health-check": TaskConfig(
            ...            name="health-check",
            ...            type=TaskType.AUTOMATED,
            ...            frequency=7,
            ...            description="...",
            ...            enabled=True
            ...        ),
            ...        "mirrorlist-update": TaskConfig(
            ...            name="mirrorlist-update",
            ...            type=TaskType.MANUAL,
            ...            frequency=15,
            ...            description="...",
            ...            enabled=False
            ...        ),
            ...    }
            ... )
            >>> enabled_tasks = tasks_config.get_enabled_tasks()
            >>> print(tuple(enabled_tasks.keys()))
            ('health-check',)
        """
        return {name: task for name, task in self.tasks.items() if task.enabled}

    def get_tasks_by_type(self, task_type: str) -> dict[str, TaskConfig]:
        """
        Get tasks filtered by type

        Returns tasks matching type and enabled=True.

        Args:
            task_type (str): "automated" or "manual" (case-sensitive)

        Returns:
            (dict[str, TaskConfig]): Mapping of task names to their configurations

        Raises:
            InvalidTaskTypeFilterError: If task_type is not 'automated' or 'manual'.

        Examples:
            >>> from archcare.config.models import TasksConfig
            >>> config = TasksConfig(
            ...    tasks={
            ...        "health-check": TaskConfig(
            ...            name="health-check",
            ...            type=TaskType.AUTOMATED,
            ...            frequency=7,
            ...            description="...",
            ...            enabled=True
            ...        ),
            ...        "mirrorlist-update": TaskConfig(
            ...            name="mirrorlist-update",
            ...            type=TaskType.MANUAL,
            ...            frequency=15,
            ...            description="...",
            ...            enabled=True
            ...        ),
            ...    }
            ... )
            >>> auto = config.get_tasks_by_type("automated")
            >>> print(tuple(auto.keys()))
            ('health-check',)
            >>> manual = config.get_tasks_by_type("manual")
            >>> print(tuple(manual.keys()))
            ('mirrorlist-update',)
        """
        if task_type not in ["automated", "manual"]:
            raise InvalidTaskTypeFilterError(task_type)
        return {
            name: task
            for name, task in self.tasks.items()
            if str(task.task_type) == task_type and task.enabled
        }

    def get_task(self, name: str) -> TaskConfig:
        """
        Get a specific task by name

        Returns a single task by name, even if disabled.

        Args:
            name (str): Exact task name (must exist)

        Returns:
            (TaskConfig): The configuration for the requested task

        Raises:
            UnknownTaskError: If the task does not exist.

        Examples:
            >>> from archcare.config.models import TasksConfig
            >>> config = TasksConfig(
            ...    tasks={
            ...        "health-check": TaskConfig(
            ...            name="health-check",
            ...            type=TaskType.AUTOMATED,
            ...            frequency=7,
            ...            description="...",
            ...            enabled=True
            ...        ),
            ...        "mirrorlist-update": TaskConfig(
            ...            name="mirrorlist-update",
            ...            type=TaskType.MANUAL,
            ...            frequency=15,
            ...            description="...",
            ...            enabled=True
            ...        ),
            ...    }
            ... )
            >>> task_cfg = config.get_task("health-check")
            >>> print(task_cfg.frequency)
            7
        """
        task_name = self.tasks.get(name)
        if not task_name:
            raise UnknownTaskError(name)
        return task_name


class IgnoredServicesConfig(BaseModel):
    """
    Configuration for services to ignore in `failed-services` task

    Part of tasks configuration; allows users to exclude specific systemd services
    from the `failed-services` task. Useful for services that are expected to fail or
    restart frequently and don't need monitoring.

    Attributes:
        services (list[str]): List of systemd service names to ignore during the check.
                 Empty list means no services are ignored (all are monitored)

    Validation:
        - Each service name must be a valid systemd unit name (alphanumeric, dots, hyphens)
        - Invalid names raise InvalidUnitNameError with list of offending names
        - Names are case-sensitive; "nginx" != "Nginx"

    Example Configuration:
        ```toml title="ignored-services.toml"
        services = [
            "custom-watchdog.service",  # Custom app that's expected to fail
        ]
        ```

    Methods:
        is_ignored: Check if a service should be ignored.

    Edge Cases:
        - Service listed but not installed: No effect (validation passes)
        - Typo in service name: Task will never find it; recommend validation on save
    """

    services: list[str] = Field(
        default_factory=list, description="List of systemd service names to ignore"
    )

    @field_validator("services")
    @classmethod
    def validate_service_names(cls, v: list[str]) -> list[str]:
        invalid = [name for name in v if not is_valid_systemd_unit_name(name)]
        if invalid:
            raise InvalidUnitNameError(invalid)
        return v

    def is_ignored(self, service_name: str) -> bool:
        """
        Check if a service should be ignored

        Checks whether the systemd service should be ignored in the check.

        Args:
            service_name (str): Systemd unit name

        Returns:
            (bool): True if service is in ignore list, False otherwise

        Examples:
            >>> ignored_cfg = IgnoredServicesConfig(services=["watchdog.service"])
            >>> if not ignored_cfg.is_ignored("nginx.service"):
            ...    print(f"Failed service: nginx")  # Printed
            Failed service: nginx
            >>> if not ignored_cfg.is_ignored("watchdog.service"):
            ...    print(f"Failed service: watchdog")  # Not printed if ignored
        """
        return service_name in self.services


class MirrorlistSettings(BaseModel):
    """
    Settings for `mirrorlist-update` task

    Configures how the `mirrorlist-update` task downloads and ranks Arch Linux
    package mirrors. Uses [Reflector](https://wiki.archlinux.org/title/Reflector)
    behind the scenes to fetch and rank mirrors based on country, protocol, and
    sync recency.

    Attributes:
        path (pathlib.Path): Path to write the updated mirrorlist file.
            Defaults to `/etc/pacman.d/mirrorlist`.

        country (str | list[str]): Country/countries for mirror selection (single string or list).
            Supports ISO 3166 country codes (e.g., "DE" for Germany). Defaults to "Germany".
            ```sh
            # Available countries
            reflector --list-countries
            ```

        protocol (str): Transfer protocol for mirrors. Defaults to "https".

            - "http": Use HTTP protocol (unencrypted, unsafe)
            - "https": Use HTTPS protocol (encrypted, recommended)
            - "rsync": Use Rsync protocol (needs proper configuration as it may be disabled)

        sort: Ranking criterion for returned mirrors. Must be one of "age", "rate", "country",
            "score", "delay". Defaults to "rate" (download speed).
            See [Reflector docs](https://xyne.dev/projects/reflector/) for details on
            each sort option.

        latest: Number of most recently synced mirrors to consider (Range: 1-50 | Default: 20).

        number_of_mirrors: Final count of mirrors to include in `/etc/pacman.d/mirrorlist`
            (Range: 1-50 | Default: 5)

            Typical: 5-15 mirrors balances redundancy and performance

    Example Configurations:
        ```toml title="settings.toml"
        # Conservative: 3 fast, recent German mirrors
        [mirrorlist]
        country = "Germany"
        protocol = "https"
        sort = "rate"
        latest = 15
        number_of_mirrors = 3

        # Balanced: 5 mirrors from 3 countries, ranked by score
        [mirrorlist]
        country = ["Germany", "Netherlands", "France"]
        protocol = "https"
        sort = "score"
        latest = 20
        number_of_mirrors = 5

        # Redundant: 15 mirrors, prefer recent syncs
        [mirrorlist]
        country = "Germany"
        protocol = "https"
        sort = "age"
        latest = 30
        number_of_mirrors = 15
        ```

    Validation:
        - protocol must be one of: "http", "https", "rsync"
        - sort must be one of: "age", "rate", "country", "score", "delay"
        - latest and number_of_mirrors are integers in [1, 50]

    Integration:
        - `mirrorlist-update` task uses these settings to construct reflector command
        - Output written to path (requires sudo on typical systems)
        - Logs reflect country, sort, latest for audit trail

    Troubleshooting:
        - "No mirrors found": Relax latest or sort criteria
        - "Too slow": Reduce number_of_mirrors or prefer "score" sort. See
            [mirror status page](https://archlinux.org/mirrors/status/) for details
            on how it's calculated.
    """

    path: Path = Field(
        default=Path("/etc/pacman.d/mirrorlist"),
        description="Path to store the mirrorlists",
    )
    country: str | list[str] = Field(default="Germany", description="Country for mirror selection")
    protocol: str = Field(default="https", description="Protocol to use (http/https/rsync)")
    sort: str = Field(default="rate", description="The criteria to sort the mirrors with")
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
        """Validate protocol value"""
        if v not in ["http", "https", "rsync"]:
            raise ValueError("protocol must be 'http', 'https', or 'rsync'")
        return v

    @field_validator("sort")
    @classmethod
    def validate_sort(cls, v: str) -> str:
        """Validate sort value"""
        valid_sorts = ["age", "rate", "country", "score", "delay"]
        if v not in valid_sorts:
            raise ValueError(f"sort must be one of {valid_sorts}")
        return v

    @field_serializer("path")
    def serialize_path(self, v: Path) -> str:
        """Serialize the mirrorlist path to a string for TOML compatibility"""
        return str(v)


class MaintenanceCheckSettings(BaseModel):
    """
    Settings for `maintenance-check` task

    Configures the `maintenance-check` task, including the threshold days for `WARNING`
    and `CRITICAL` alerts, output mode, and report retention.

    Attributes:
        critical_threshold_days (int): Days overdue before task flagged as CRITICAL. (Default: 7)

        warning_threshold_days (int): Days overdue before task flagged as WARNING. (Default: 0)

        output_mode (str): Where to write maintenance check report. (Default: "terminal")

              - "terminal": Print to console
              - "file": Write to `~/.local/state/archcare/reports/maintenance-check-*.txt`
              - "both": Both terminal and file

        show_notifications (bool): Send desktop notifications for overdue tasks. (Default: True)

        notification_level (str): Minimum severity to trigger notifications. (Defualt: "warning")

            - "critical": Only notify if critical (doesn't notify on warnings)
            - "warning": Notify if warning or critical
            - "info": Notify on any finding (verbose)

        report_retention_days (int): Number of days to keep the report files. (Default: 30)

        require_acknowledgment (bool): Require user to acknowledge critical issues
            before proceeding. (Default: True)

    Example Configurations:
        ```toml title="settings.toml"
        # Strict monitoring: Warn at 1 day, critical at 7 days
        [maintenance_check]
        critical_threshold_days = 7
        warning_threshold_days = 1
        output_mode = "both"
        show_notifications = true
        notification_level = "warning"

        # Relaxed: Only care about critical overages
        [maintenance_check]
        critical_threshold_days = 14
        warning_threshold_days = 0
        output_mode = "terminal"
        show_notifications = true
        notification_level = "critical"

        # Silent mode: Log only, no notifications
        [maintenance_check]
        critical_threshold_days = 7
        warning_threshold_days = 0
        output_mode = "file"
        show_notifications = false
        require_acknowledgment = false
        ```

    Validation:
        - `output_mode` must be one of: "terminal", "file", "both"
        - `notification_level` must be one of: "critical", "warning", "info"
        - `critical_threshold_days` >= 0
        - `report_retention_days` >= 1 (at least 1 day)

    State Tracking:
        - Reports saved to `~/.local/state/archcare/reports/maintenance-check-YYYY-MM-DD.txt`
        - Old reports automatically deleted per `report_retention_days`
        - Each report includes task name, last run, next due, days overdue, and severity
    """

    critical_threshold_days: int = Field(
        default=7, ge=0, description="Days overdue before task is considered critical"
    )
    warning_threshold_days: int = Field(
        default=0, ge=0, description="Days overdue before task is considered warning"
    )
    output_mode: str = Field(
        default="terminal", description="Output mode: 'terminal', 'file', or 'both'"
    )
    show_notifications: bool = Field(default=True, description="Show desktop notifications")
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
        """Validate output mode value"""
        valid_modes = ["terminal", "file", "both"]
        if v not in valid_modes:
            raise ValueError(f"output_mode must be one of: {', '.join(valid_modes)}")
        return v

    @field_validator("notification_level")
    @classmethod
    def validate_notification_level(cls, v: str) -> str:
        """Validate notification level value"""
        valid_levels = ["critical", "warning", "info"]
        if v not in valid_levels:
            raise ValueError(f"notification_level must be one of: {', '.join(valid_levels)}")
        return v


class AppSettings(BaseModel):
    """
    Application-wide settings

    Master configuration loaded from `settings.toml`. Combines global settings
    (logging, user, behavior) with task-specific settings. Provides computed paths
    for state, logs, config, and reports directories.

    Attributes:
        user (str): The username. Set by [UserContext][archcare.utils.user.UserContext] and
            used to resolve the home directory at runtime.

        log_retention_days (int): Age threshold for log file cleanup. (Default: 30)

        log_level (LogLevel): Logging verbosity.

        dry_run (bool): Simulate operations without making changes

        mirrorlist (MirrorlistSettings): Mirrorlist settings (see class for details)
        maintenance_check (MaintenanceCheckSettings): Maintenance check settings
            (see class for details)

    Methods:
        home_dir: *(property)* User's home directory

        log_dir: *(property)* Log directory

        state_file: *(property)* State file path

        config_dir: *(property)* Config directory

        report_dir: *(property)* Report file directory

        ensure_directories: Create necessary directories if missing.
            Called during app initialization; idempotent (safe to call multiple times).

    Example Configuration:
        ```toml title="settings.toml"
        log_retention_days = 30        # Keep 1 month of logs
        log_level = "INFO"             # Standard verbosity
        dry_run = false                # Actually run tasks

        [mirrorlist]
        country = "Germany"
        number_of_mirrors = 5

        [maintenance_check]
        critical_threshold_days = 7
        warning_threshold_days = 1
        show_notifications = true
        ```

    Validation:
        - `home_dir` resolution requires user to exist (`pwd.getpwnam` check)
        - All computed paths must be absolute (enforced by [validate_paths][validate_paths])
        - Paths validated for syntax (resolvable) without requiring existence
        - [HomeDirectoryResolutionError][archcare.config.exceptions.HomeDirectoryResolutionError]
            raised if user lookup fails

    Examples:
        >>> settings = AppSettings() # Create default settings
        >>> print(settings.log_level)
        INFO
        >>> print(settings.mirrorlist.protocol)
        https
    """

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
    dry_run: bool = Field(default=False, description="Simulate operations without making changes")

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
    @computed_field
    @property
    def home_dir(self) -> Path:
        """
        Home directory of the user

        Uses `pwd.getpwnam` for robust resolution instead of hardcoded `/home/` paths.

        Resolution priority:
            1. `SUDO_USER`'s home (if running via sudo)
            2. `self.user`'s home (if `ARCHCARE_USER` or explicitly set)
            3. Current user's home (interactive fallback)
        """
        sudo_user = getenv("SUDO_USER")
        if sudo_user:
            return self._resolve_user_home(sudo_user)

        if self.user:
            return self._resolve_user_home(self.user)

        return Path.home()

    @staticmethod
    def _resolve_user_home(username: str) -> Path:
        """
        Resolve a user's home directory using pwd, with fallback

        Args:
            username: The username to look up.

        Returns:
            Path to the user's home directory.

        Raises:
            HomeDirectoryResolutionError: If the user does not exist or
                home cannot be resolved.
        """
        try:
            return Path(getpwnam(username).pw_dir)
        except KeyError:
            # Fallback: try common path for systems where pwd might not work
            fallback = Path(f"/home/{username}")
            if fallback.exists():
                return fallback
            raise HomeDirectoryResolutionError(username) from KeyError(username)

    @computed_field
    @property
    def log_dir(self) -> Path:
        """
        Directory for log files

        Location: `~/.local/state/archcare/logs`

        Created by [ensure_directories][ensure_directories] if missing. Contains task-specific
        and Archcare master log files. Old logs cleaned up based on `log_retention_days` setting.

        Example:
            ```ansi
            ~/.local/state/archcare/logs/
            ├── archcare.log
            └── tasks
                ├── failed-services.log
                ├── health-check.log
                ├── maintenance-check.log
                └── mirrorlist-update.log
            ```
        """
        return self.home_dir / ".local/state/archcare/logs"

    @computed_field
    @property
    def state_file(self) -> Path:
        """
        File to track task execution state

        Location: `~/.local/state/archcare/state.json`

        Persists [AppState][AppState] for app state management. Created by
        [ConfigLoader][archcare.config.loader.ConfigLoader] and updated after
        each task execution. Enables scheduling decisions.

        Example content:
            ```json title="state.json"
            {
                "tasks": {
                    "health-check": {
                        "last_run": "2025-08-17T10:30:00",
                        "last_status": "success",
                        "next_due": "2025-08-24T10:30:00",
                        "run_count": 52
                    }
                },
                "last_updated": "2025-08-17T10:30:00"
            }
            ```
        """
        return self.home_dir / ".local/state/archcare/state.json"

    @computed_field
    @property
    def config_dir(self) -> Path:
        """
        Configuration directory

        Location: `~/.config/archcare`

        Created by [ensure_directories][ensure_directories] if missing.
        Default config files are created with
        [create_default_config_files][archcare.config.loader.create_default_config_files].

        Example:
            ```ansi
            ~/.config/archcare/
            ├── tasks.toml      (task definitions)
            └── settings.toml   (application settings)
            ```
        """
        return self.home_dir / ".config/archcare"

    @computed_field
    @property
    def report_dir(self) -> Path:
        """
        Directory for maintenance check reports

        Location: `~/.local/state/archcare/reports`

        Created by [ensure_directories][ensure_directories] if missing.
        Stores `maintenance-check` task timestamped reports.
        Old reports auto-cleaned per `report_retention_days`.

        Example:
            ```ansi
            ~/.local/state/archcare/reports/
            ├── maintenance-check_20260715_010211.txt
            ├── maintenance-check_20260717_010914.txt
            └── maintenance-check_20260718_163151.txt
            ```
        """
        return self.home_dir / ".local/state/archcare/reports"

    @model_validator(mode="after")
    def validate_paths(self) -> Self:
        """
        Validate that all computed paths are absolute and well-formed

        Checks:
            - Paths are absolute (not relative)
            - Paths are syntactically valid (resolvable without requiring existence)

        Does NOT create directories; [ensure_directories][ensure_directories] handles that.

        Raises:
            ValueError: If any path is relative or malformed
        """
        paths = [
            self.log_dir,
            self.state_file,
            self.config_dir,
            self.report_dir,
        ]

        for path in paths:
            if not path.is_absolute():
                raise ValueError(f"Path must be absolute: {path}")

            # resolve(strict=False) validates path syntax and resolves ., .., ~
            # without requiring the path to actually exist on disk
            try:
                path.resolve(strict=False)
            except (OSError, RuntimeError) as e:
                raise ValueError(f"Malformed path {path}: {e}") from e

        return self

    @field_serializer("log_level")
    def serialize_log_level(self, log_level: LogLevel) -> str:
        """Serialize log level as a string."""
        return str(log_level)

    def ensure_directories(self) -> None:
        """
        Create necessary directories if they don't exist

        Called during app initialization to set up the directory structure.

        Idempotent: safe to call multiple times.

        Creates:
            - `log_dir`: For storing log files
            - `state_file.parent`: For storing `state.json`
            - `config_dir`: For `tasks.toml` and `settings.toml`
            - `report_dir`: For `maintenance-check` task reports

        Raises:
            OSError: If mkdir fails (e.g., permission denied on parent dir)
        """
        paths = [
            self.log_dir,
            self.state_file.parent,
            self.config_dir,
            self.report_dir,
        ]
        for path in paths:
            path.mkdir(parents=True, exist_ok=True)


class TaskState(BaseModel):
    """
    Runtime state for a task

    Tracks the execution history of a single task. One `TaskState` exists per
    task (same key as [TaskConfig][TaskConfig] in the registry) and is persisted
    in `state.json`. Aggregated by [AppState][AppState].

    Attributes:
        last_run (datetime.datetime | None): Timestamp of most recent execution attempt
            (success or failure) or `None` if task never ran.

        last_status (TaskStatus | None): Outcome of most recent execution or `None` if never run.

        next_due (datetime.datetime | None): Timestamp when task should run next or
            `None` if never calculated (task never run or disabled).

            Calculated as: `last_run` + frequency days (from [TaskConfig][TaskConfig])

        run_count (int): Total number of times task has been executed. Incremented by
            [TaskExecutor][archcare.core.executor.TaskExecutor] after each run.

        last_error (str | None): Error message from most recent failed run or
            `None` if `last_status` is not `FAILURE`.

        skip_reason (SkipReason | None): Reason task was skipped
            (if `last_status` is `SKIPPED`) or `None` if `last_status`
            is not `SKIPPED`.

    JSON Persistence:
        Stored in `~/.local/state/archcare/state.json` as part of [AppState][AppState].
        Serialized with datetime objects converted to ISO 8601 strings.
        Deserialized on app startup to restore history.

    Example:
        ```json title="state.json"
        {
            "tasks": {
                "health-check": {
                    "last_run": "2025-08-17T10:30:00",
                    "last_status": "success",
                    "next_due": "2025-08-24T10:30:00",
                    "run_count": 52,
                    "last_error": null,
                    "skip_reason": null
                }
            },
            "last_updated": "2025-08-17T10:30:00"
        }
        ```
    """

    last_run: datetime | None = Field(None, description="Timestamp of last execution")
    last_status: TaskStatus | None = Field(None, description="Status of last execution")
    next_due: datetime | None = Field(None, description="When task should run next")
    run_count: int = Field(
        default=0, ge=0, description="Total number of times task has been executed"
    )
    last_error: str | None = Field(None, description="Error message from last failed run")
    skip_reason: SkipReason | None = Field(None, description="Reason why task was skipped")


class AppState(BaseModel):
    """
    Application state tracking task execution history

    Master state object persisted in `~/.local/state/archcare/state.json`.
    Combines [TaskState][TaskState] for all registered tasks; reconstructed
    on app startup from the JSON file. Updated by
    [TaskExecutor][archcare.core.executor.TaskExecutor] after each task run.

    Attributes:
        tasks (dict[str, TaskState]): Dict mapping task names (str) to `TaskState` objects.
            One entry per registered task (from [TaskConfig][TaskConfig])
            `TaskState` created lazily on first access via [get_task_state][get_task_state].

        last_updated: Timestamp of last state modification Auto-updated by
            [update_task_state][update_task_state].

    Methods:
        get_task_state: Get state for a task, creating if it doesn't exist.
        update_task_state: Update state after task execution.

    JSON Persistence Format:
        ```json
        {
            "tasks": {
                "health-check": {
                    "last_run": "2025-08-17T10:00:00",
                    "last_status": "success",
                    "next_due": "2025-08-24T10:00:00",
                    "run_count": 3,
                    "last_error": null,
                    "skip_reason": null
                },
                "mirrorlist-update": {
                    "last_run": null,
                    "last_status": null,
                    "next_due": null,
                    "run_count": 0,
                    "last_error": null,
                    "skip_reason": null
                }
            },
            "last_updated": "2025-08-17T10:30:00"
        }
        ```
    """

    tasks: dict[str, TaskState] = Field(
        default_factory=dict, description="Map of task name to task state"
    )
    last_updated: datetime = Field(
        default_factory=datetime.now, description="Last time state was updated"
    )

    def get_task_state(self, task_name: str) -> TaskState:
        """
        Get state for a task, creating if it doesn't exist

        Args:
            task_name (str): Name of the task (must match [TaskConfig][TaskConfig] key)

        Returns:
            Corresponding `TaskState` object, lazily created if it doesn't exist
        """
        if task_name not in self.tasks:
            self.tasks[task_name] = TaskState()
        return self.tasks[task_name]

    def update_task_state(
        self,
        task_name: str,
        status: TaskStatus,
        next_due: datetime | None = None,
        error: str | None = None,
        skip_reason: SkipReason | None = None,
    ) -> None:
        """
        Update state after task execution

        Args:
            task_name (str): Name of the task (must match TaskConfig key)
            status (TaskStatus): Outcome of task execution
            next_due (datetime.datetime | None): When to run next
            error (str | None): Error message if `FAILURE` (optional)
            skip_reason (SkipReason | None): Why skipped if `SKIPPED` (optional)
        """
        state = self.get_task_state(task_name)
        state.last_run = datetime.now()
        state.last_status = status
        state.next_due = next_due
        state.run_count += 1
        state.last_error = error
        state.skip_reason = skip_reason
        self.last_updated = datetime.now()
