"""
Per-task detail schemas for Archcare.

Concrete dataclasses describing the `details` payload each task produces.
Tasks construct one of these explicitly and pass it to a
[TaskResult][] factory
(`success`, `failed`, `skipped`, `partial`).

Each task type has a dedicated details class:

- `FailedServicesDetails`: Failed systemd services with diagnostic info
- `HealthCheckDetails`: System health metrics (disk, memory, CPU, filesystem, pacman)
- `MirrorlistUpdateDetails`: Mirrorlist update results with before/after comparison
- `MaintenanceCheckDetails`: Scheduled task status with severity categorization

These frozen dataclasses ensure immutability and type safety throughout the
execution pipeline.

Examples:
    >>> from archcare.core.task_details import FailedServicesDetails, FailedServiceInfo
    >>> from archcare.core.models import TaskResult, success
    >>>
    >>> info = FailedServiceInfo(service="nginx.service", description="Failed to start")
    >>> details = FailedServicesDetails(
    ...     total_failed=1,
    ...     actual_failures=1,
    ...     failed_services=[info]
    ... )
    >>> result = success("Check complete", details=details)
    >>> result.details.total_failed
    1

See Also:
    - [TaskResult][archcare.core.models.TaskResult]: Generic result container using these details
    - [FailedServicesTask][archcare.tasks.failed_services.FailedServicesTask]:
        Produces `FailedServicesDetails`
    - [HealthCheckTask][archcare.tasks.health_check.HealthCheckTask]: Produces `HealthCheckDetails`
    - [MirrorlistUpdateTask][archcare.tasks.mirrorlist_update.MirrorlistUpdateTask]:
        Produces `MirrorlistUpdateDetails`
    - [MaintenanceCheckTask][archcare.tasks.maintenance_check.MaintenanceCheckTask]:
        Produces `MaintenanceCheckDetails`
"""

from dataclasses import dataclass, field

from archcare.utils.info_models import MirrorlistInfo

from .models import MaintenanceIssue


@dataclass(frozen=True)
class FailedServiceInfo:
    """
    A single failed systemd service and its diagnostic details.

    Captures the state of a failed unit as reported by `systemctl show`
    and journal logs. Used as list items in `failed_services` attribute
    of [FailedServicesDetails][].

    Attributes:
        service (str): The systemd unit name (e.g., "nginx.service").
        description (str): Human-readable description from systemd, if available.
            Defaults to empty string.
        active (str): The active state from systemd ("active", "inactive", "failed",
            "activating", "deactivating"). Defaults to "unknown".
        main_pid (int | None): Main process ID if the service was running.
            `None` if not available or service never started.
        logs (list[str]): Recent journal log lines for this service.
            Collected via `journalctl -u <service> -n 10 --no-pager`.
            Defaults to empty list.

    Examples:
        >>> from archcare.core.task_details import FailedServiceInfo
        >>> info = FailedServiceInfo(
        ...     service="nginx.service",
        ...     description="A high performance web server",
        ...     active="failed",
        ...     main_pid=1234,
        ...     logs=["systemd[1]: Failed to start A high performance web server"]
        ... )
        >>> info.service
        'nginx.service'
        >>> info.active
        'failed'

    See Also:
        - [FailedServicesDetails][]: Container for multiple services
        - [FailedServicesTask][archcare.tasks.failed_services.FailedServicesTask]:
            Task that produces this
    """

    service: str
    description: str = ""
    active: str = "unknown"
    main_pid: int | None = None
    logs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FailedServicesDetails:
    """
    Details produced by
    [FailedServicesTask.execute][archcare.tasks.failed_services.FailedServicesTask.execute].

    Aggregates the results of scanning all systemd units for failures.
    Separates actual failures from ignored services (configured in
    `ignored-services.toml`) for accurate reporting.

    Attributes:
        total_failed (int): Total number of failed units found by systemd,
            including ignored ones.
        actual_failures (int): Number of failed units not in the ignore list.
            This is the count that determines task status (0 = success, >0 = failure).
        ignored (int): Number of failed units that match entries in the
            ignore list. These are tracked for auditing but don't affect status.
        ignored_services (list[str]): Names of the ignored failed services.
        failed_services (list[FailedServiceInfo]): Full diagnostic details for
            each non-ignored failed service. Empty if `actual_failures == 0`.

    Status Logic:
        - `actual_failures == 0` and `total_failed == 0`: `SUCCESS` (no failures)
        - `actual_failures == 0` and `total_failed > 0`: `SUCCESS` (all ignored)
        - `actual_failures > 0`: FAILURE (unignored failures exist)

    Examples:
        >>> from archcare.core.task_details import FailedServicesDetails, FailedServiceInfo
        >>> info = FailedServiceInfo(service="nginx.service", active="failed")
        >>> details = FailedServicesDetails(
        ...     total_failed=2,
        ...     actual_failures=1,
        ...     ignored=1,
        ...     ignored_services=["systemd-networkd-wait-online.service"],
        ...     failed_services=[info]
        ... )
        >>> details.actual_failures
        1

    See Also:
        - [FailedServiceInfo][]: Individual service details
        - [FailedServicesTask][archcare.tasks.failed_services.FailedServicesTask]: Producer task
        - [IgnoredServicesConfig][archcare.config.models.IgnoredServicesConfig]:
            Ignore list configuration
    """

    total_failed: int = 0
    actual_failures: int = 0
    ignored: int = 0
    ignored_services: list[str] = field(default_factory=list)
    failed_services: list[FailedServiceInfo] = field(default_factory=list)


@dataclass(frozen=True)
class MaintenanceCheckSummary:
    """
    The `summary` sub-structure within [MaintenanceCheckDetails][].

    Provides aggregated counts of issues by severity and computed properties
    for quick status checks and human-readable messages.

    Attributes:
        total_tasks_monitored (int): Number of tasks checked for due status.
        critical_count (int): Tasks overdue by `critical_threshold_days` or more.
        warning_count (int): Tasks overdue by `warning_threshold_days` or more
            (but less than critical threshold).
        info_count (int): Tasks that are due or slightly overdue but below
            warning threshold.

    Methods:
        total_issues (int): *(property)* Sum of critical, warning, and info counts.
        has_issues (bool): *(property)* True if any issues exist (any count > 0).
        summary_message (str): *(property)* Human-readable summary for display/logging.

    Examples:
        >>> from archcare.core.task_details import MaintenanceCheckSummary
        >>> summary = MaintenanceCheckSummary(
        ...     total_tasks_monitored=5,
        ...     critical_count=1,
        ...     warning_count=2,
        ...     info_count=0
        ... )
        >>> summary.total_issues
        3
        >>> summary.has_issues
        True
        >>> summary.summary_message
        'Found 1 critical, 2 warning issue(s) requiring attention'
        >>> MaintenanceCheckSummary().summary_message
        'All maintenance tasks are up to date!'

    See Also:
        - [MaintenanceCheckDetails][]: Parent container
        - [MaintenanceCheckSettings][archcare.config.models.MaintenanceCheckSettings]:
            Threshold configuration
    """

    total_tasks_monitored: int = 0
    critical_count: int = 0
    warning_count: int = 0
    info_count: int = 0

    @property
    def total_issues(self) -> int:
        """
        Total number of issues across all severity levels.

        Returns:
            int: Sum of `critical_count`, `warning_count`, and `info_count`.

        Examples:
            >>> from archcare.core.task_details import MaintenanceCheckSummary
            >>> MaintenanceCheckSummary(critical_count=2, warning_count=1).total_issues
            3
        """
        return self.critical_count + self.warning_count + self.info_count

    @property
    def has_issues(self) -> bool:
        """
        Check if any issues exist.

        Returns:
            bool: True if at least one issue (critical, warning, or info) exists.

        Examples:
            >>> from archcare.core.task_details import MaintenanceCheckSummary
            >>> MaintenanceCheckSummary().has_issues
            False
            >>> MaintenanceCheckSummary(info_count=1).has_issues
            True
        """
        return self.critical_count != 0 or self.warning_count != 0 or self.info_count != 0

    @property
    def summary_message(self) -> str:
        """
        Human-readable summary message for display/logging.

        Returns:
            str: Descriptive message listing issue counts by severity,
                or "All maintenance tasks are up to date!" if no issues.

        Examples:
            >>> from archcare.core.task_details import MaintenanceCheckSummary
            >>> MaintenanceCheckSummary().summary_message
            'All maintenance tasks are up to date!'
            >>> MaintenanceCheckSummary(critical_count=1).summary_message
            'Found 1 critical issue(s) requiring attention'
            >>> MaintenanceCheckSummary(warning_count=2, info_count=1).summary_message
            'Found 2 warning, 1 info issue(s) requiring attention'
        """
        if not self.has_issues:
            return "All maintenance tasks are up to date!"

        parts = []
        if self.critical_count:
            parts.append(f"{self.critical_count} critical")
        if self.warning_count:
            parts.append(f"{self.warning_count} warning")
        if self.info_count:
            parts.append(f"{self.info_count} info")

        return f"Found {', '.join(parts)} issue(s) requiring attention"


@dataclass(frozen=True)
class MaintenanceCheckDetails:
    """
    Details produced by
    [MaintenanceCheckTask.execute][archcare.tasks.maintenance_check.MaintenanceCheckTask.execute].

    Contains categorized lists of overdue tasks by severity level, plus a
    computed summary for quick status assessment.

    Attributes:
        critical_issues (list[MaintenanceIssue]): Tasks critically overdue.
            Each issue contains task name, days overdue, and severity.
        warning_issues (list[MaintenanceIssue]): Tasks in warning zone.
        info_issues (list[MaintenanceIssue]): Tasks due or slightly overdue.
        summary (MaintenanceCheckSummary): Aggregated counts and message.

    Methods:
        tasks_needing_attention (list[MaintenanceIssue]): *(property)* Combined list of
            critical and warning issues (excludes info-level).

    Examples:
        >>> from archcare.core.task_details import MaintenanceCheckDetails, MaintenanceCheckSummary
        >>> from archcare.core.models import MaintenanceIssue, IssueSeverity
        >>> from datetime import datetime
        >>>
        >>> issue = MaintenanceIssue(
        ...     task_name="health-check",
        ...     severity=IssueSeverity.CRITICAL,
        ...     description="Health check is 10 days overdue",
        ...     days_overdue=10,
        ...     last_run=datetime(2024, 1, 1),
        ...     last_status=None,
        ...     recommendation="Run health check immediately"
        ... )
        >>> summary = MaintenanceCheckSummary(
        ...     total_tasks_monitored=5,
        ...     critical_count=1,
        ...     warning_count=2,
        ...     info_count=0
        ... )
        >>> details = MaintenanceCheckDetails(
        ...     critical_issues=[issue],
        ...     summary=summary
        ... )
        >>> details.tasks_needing_attention
        [...MaintenanceIssue...]
        >>> len(details.tasks_needing_attention)
        1

    See Also:
        - [MaintenanceCheckSummary][]: Summary sub-structure
        - [MaintenanceIssue][]: Individual issue details
        - [MaintenanceCheckTask][archcare.tasks.maintenance_check.MaintenanceCheckTask]:
            Producer task
    """

    critical_issues: list[MaintenanceIssue] = field(default_factory=list)
    warning_issues: list[MaintenanceIssue] = field(default_factory=list)
    info_issues: list[MaintenanceIssue] = field(default_factory=list)

    summary: MaintenanceCheckSummary = field(default_factory=MaintenanceCheckSummary)

    @property
    def tasks_needing_attention(self) -> list[MaintenanceIssue]:
        """
        Combined list of critical and warning issues requiring action.

        Excludes info-level issues which are informational only.

        Returns:
            (list[MaintenanceIssue]): Concatenation of `critical_issues` and `warning_issues`.

        Examples:
            >>> from archcare.core.task_details import (
            ...     MaintenanceCheckDetails,
            ...     MaintenanceCheckSummary
            ... )
            >>> from archcare.core.models import MaintenanceIssue, IssueSeverity
            >>> from datetime import datetime
            >>>
            >>> crit = MaintenanceIssue(
            ...     task_name="a",
            ...     severity=IssueSeverity.CRITICAL,
            ...     description="Task a is overdue",
            ...     days_overdue=10,
            ...     last_run=None,
            ...     last_status=None,
            ...     recommendation="Run task a"
            ... )
            >>> warn = MaintenanceIssue(
            ...     task_name="b",
            ...     severity=IssueSeverity.WARNING,
            ...     description="Task b is overdue",
            ...     days_overdue=5,
            ...     last_run=None,
            ...     last_status=None,
            ...     recommendation="Run task b"
            ... )
            >>> info = MaintenanceIssue(
            ...     task_name="c",
            ...     severity=IssueSeverity.INFO,
            ...     description="Task c is due",
            ...     days_overdue=1,
            ...     last_run=None,
            ...     last_status=None,
            ...     recommendation="Run task c"
            ... )
            >>> details = MaintenanceCheckDetails(
            ...     critical_issues=[crit],
            ...     warning_issues=[warn],
            ...     info_issues=[info]
            ... )
            >>> len(details.tasks_needing_attention)
            2
        """
        return self.critical_issues + self.warning_issues


@dataclass(frozen=True)
class HealthCheckSummary:
    """
    The `summary` sub-structure within [HealthCheckDetails][].

    Aggregates key system health metrics into a single snapshot for quick
    assessment and display.

    Attributes:
        disk_usage_percent (float): Highest disk usage percentage across
            all monitored mount points. 0.0 if no data.
        memory_usage_percent (float): System memory usage percentage.
            0.0 if unavailable.
        cpu_usage_percent (float): Current CPU usage percentage (1-second sample).
            0.0 if unavailable.
        filesystem_errors_count (int): Number of filesystem errors detected
            (e.g., Btrfs scrub errors, ext4 corruption).
        pacman_healthy (bool): True if pacman database integrity check passed.
        packages_healthy (bool): True if package file integrity check passed
            (no missing/modified files from packages).
        uptime (str): Human-readable system uptime string (e.g., "5 days, 3:42").
            "unknown" if unavailable.

    Examples:
        >>> from archcare.core.task_details import HealthCheckSummary
        >>> summary = HealthCheckSummary(
        ...     disk_usage_percent=45.5,
        ...     memory_usage_percent=62.3,
        ...     cpu_usage_percent=12.1,
        ...     filesystem_errors_count=0,
        ...     pacman_healthy=True,
        ...     packages_healthy=True,
        ...     uptime="5 days, 3:42"
        ... )
        >>> summary.disk_usage_percent
        45.5

    See Also:
        - [HealthCheckDetails][]: Parent container with issues/warnings
        - [HealthCheckTask][archcare.tasks.health_check.HealthCheckTask]: Producer task
    """

    disk_usage_percent: float = 0.0
    memory_usage_percent: float = 0.0
    cpu_usage_percent: float = 0.0
    filesystem_errors_count: int = 0
    pacman_healthy: bool = True
    packages_healthy: bool = True
    uptime: str = "unknown"


@dataclass(frozen=True)
class HealthCheckDetails:
    """
    Details produced by
    [HealthCheckTask.execute][archcare.tasks.health_check.HealthCheckTask.execute].

    Contains categorized issues and warnings found during health checks,
    plus a summary of key metrics.

    Attributes:
        issues (list[str]): Critical problems requiring immediate attention
            (e.g., disk > 90%, filesystem corruption, pacman DB corrupted).
        warnings (list[str]): Non-critical issues that should be monitored
            (e.g., disk 80-90%, high memory usage, package file mismatches).
        total_checks (int): Number of individual health checks performed.
        summary (HealthCheckSummary): Aggregated metrics snapshot.

    Examples:
        >>> from archcare.core.task_details import HealthCheckDetails, HealthCheckSummary
        >>> summary = HealthCheckSummary(disk_usage_percent=95.0)
        >>> details = HealthCheckDetails(
        ...     issues=["Disk / at 95% usage"],
        ...     warnings=["Memory at 85% usage"],
        ...     total_checks=5,
        ...     summary=summary
        ... )
        >>> details.issues
        ['Disk / at 95% usage']
        >>> details.total_checks
        5

    See Also:
        - [HealthCheckSummary][]: Metrics summary
        - [HealthCheckTask][archcare.tasks.health_check.HealthCheckTask]: Producer task
    """

    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    total_checks: int = 0
    summary: HealthCheckSummary = field(default_factory=HealthCheckSummary)


@dataclass(frozen=True)
class MirrorlistUpdateDetails:
    """
    Details produced by
    [MirrorlistUpdateTask.execute][archcare.tasks.mirrorlist_update.MirrorlistUpdateTask.execute].

    Captures the before/after state of the pacman mirrorlist, including
    the backup path for potential rollback.

    Attributes:
        old_mirrors (int | None): Number of mirrors in the previous mirrorlist.
            `None` if previous mirrorlist couldn't be read.
        new_mirrors (int | None): Number of mirrors in the updated mirrorlist.
            `None` if update failed or reflector didn't run.
        old_info (MirrorlistInfo): Parsed metadata from the old mirrorlist
            (countries, protocols, generation time). Defaults to empty `MirrorlistInfo`.
        new_info (MirrorlistInfo): Parsed metadata from the new mirrorlist.
            Defaults to empty `MirrorlistInfo`.
        backup_path (str | None): Path to the backup of the original mirrorlist.
            Created before update for rollback capability. `None` if backup failed
            or wasn't created.

    Rollback:
        If the update produces an undesirable mirrorlist, the original can be
        restored via:
        ```bash
        sudo cp <backup_path> /etc/pacman.d/mirrorlist
        ```

    Examples:
        >>> from archcare.core.task_details import MirrorlistUpdateDetails
        >>> from archcare.utils.info_models import MirrorlistInfo
        >>> old_info = MirrorlistInfo(total_mirrors=5, protocols={"https"})
        >>> new_info = MirrorlistInfo(total_mirrors=10, protocols={"https", "http"})
        >>> details = MirrorlistUpdateDetails(
        ...     old_mirrors=5,
        ...     new_mirrors=10,
        ...     old_info=old_info,
        ...     new_info=new_info,
        ...     backup_path="/etc/pacman.d/mirrorlist.backup.20240115"
        ... )
        >>> details.new_mirrors
        10
        >>> details.backup_path
        '/etc/pacman.d/mirrorlist.backup.20240115'

    See Also:
        - [archcare.utils.info_models.MirrorlistInfo][]: Mirrorlist metadata
        - [archcare.tasks.mirrorlist_update.MirrorlistUpdateTask][]: Producer task
        - [archcare.utils.mirrorlist][]: Mirrorlist parsing and reflector invocation
    """

    old_mirrors: int | None = None
    new_mirrors: int | None = None
    old_info: MirrorlistInfo = field(default_factory=MirrorlistInfo)
    new_info: MirrorlistInfo = field(default_factory=MirrorlistInfo)
    backup_path: str | None = None
