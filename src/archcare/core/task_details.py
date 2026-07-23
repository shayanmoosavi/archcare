"""
Per-task detail schemas.

Concrete dataclasses describing the `details` payload each task produces,
replacing free-form **kwargs dicts. Tasks construct one of these explicitly
and pass it to a TaskResult factory (success/failed/skipped/partial).
"""

from dataclasses import dataclass, field

from archcare.utils.info_models import MirrorlistInfo

from .models import MaintenanceIssue


@dataclass(frozen=True)
class FailedServiceInfo:
    """A single failed systemd service and its diagnostic details."""

    service: str
    description: str = ""
    active: str = "unknown"
    main_pid: int | None = None
    logs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FailedServicesDetails:
    """Details produced by FailedServicesTask.execute()."""

    total_failed: int = 0
    actual_failures: int = 0
    ignored: int = 0
    ignored_services: list[str] = field(default_factory=list)
    failed_services: list[FailedServiceInfo] = field(default_factory=list)


@dataclass(frozen=True)
class MaintenanceCheckSummary:
    """The `summary` sub-structure within MaintenanceCheckDetails."""

    total_tasks_monitored: int = 0
    critical_count: int = 0
    warning_count: int = 0
    info_count: int = 0

    @property
    def total_issues(self) -> int:
        return self.critical_count + self.warning_count + self.info_count

    @property
    def has_issues(self) -> bool:
        return (
            self.critical_count != 0 or self.warning_count != 0 or self.info_count != 0
        )

    @property
    def summary_message(self) -> str:
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
    """Details produced by MaintenanceCheckTask.execute()."""

    critical_issues: list[MaintenanceIssue] = field(default_factory=list)
    warning_issues: list[MaintenanceIssue] = field(default_factory=list)
    info_issues: list[MaintenanceIssue] = field(default_factory=list)

    summary: MaintenanceCheckSummary = field(default_factory=MaintenanceCheckSummary)

    @property
    def tasks_needing_attention(self) -> list[MaintenanceIssue]:
        return self.critical_issues + self.warning_issues


@dataclass(frozen=True)
class HealthCheckSummary:
    """The `summary` sub-structure within HealthCheckDetails."""

    disk_usage_percent: float = 0.0
    memory_usage_percent: float = 0.0
    cpu_usage_percent: float = 0.0
    filesystem_errors_count: int = 0
    pacman_healthy: bool = True
    packages_healthy: bool = True
    uptime: str = "unknown"


@dataclass(frozen=True)
class HealthCheckDetails:
    """Details produced by HealthCheckTask.execute()."""

    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    total_checks: int = 0
    summary: HealthCheckSummary = field(default_factory=HealthCheckSummary)


@dataclass(frozen=True)
class MirrorlistUpdateDetails:
    """Details produced by MirrorlistUpdateTask.execute()."""

    old_mirrors: int | None = None
    new_mirrors: int | None = None
    old_info: MirrorlistInfo = field(default_factory=MirrorlistInfo)
    new_info: MirrorlistInfo = field(default_factory=MirrorlistInfo)
    backup_path: str | None = None
