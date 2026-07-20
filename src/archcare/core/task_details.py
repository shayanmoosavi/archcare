"""
Per-task detail schemas.

Concrete dataclasses describing the `details` payload each task produces,
replacing free-form **kwargs dicts. Tasks construct one of these explicitly
and pass it to a TaskResult factory (success/failed/skipped/partial); the
factory flattens it into TaskResult.details for backward-compatible
consumption by existing formatters/presenters, which still read details as
a plain dict[str, Any].
"""

from dataclasses import dataclass, field
from typing import Any


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
class HealthCheckSummary:
    """The `summary` sub-structure within HealthCheckDetails."""

    disk_usage_percent: float = 0.0
    memory_usage_percent: float = 0.0
    cpu_usage_percent: float = 0.0
    filesystem_errors_count: int = 0
    pacman_healthy: bool = False
    packages_healthy: bool = False
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
    old_info: dict[str, Any] = field(default_factory=dict)
    new_info: dict[str, Any] = field(default_factory=dict)
    backup_path: str | None = None
