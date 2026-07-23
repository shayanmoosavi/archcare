"""Structured data models for return values of some utility functions."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ServiceStatusInfo:
    """Data class for service status information."""

    loaded: bool = False
    active: str = "unknown"
    running: bool = False
    description: str = ""
    main_pid: int | None = None


@dataclass(frozen=True)
class DiskUsageInfo:
    """Data class for disk usage information."""

    path: str = "/"
    total: int = 0
    used: int = 0
    free: int = 0
    percent: float = 0.0


@dataclass(frozen=True)
class MemoryInfo:
    """Data class for memory information."""

    total: int = 0
    available: int = 0
    used: int = 0
    percent: float = 0.0
    swap_total: int = 0
    swap_used: int = 0
    swap_percent: float = 0.0


@dataclass(frozen=True)
class CpuInfo:
    """Data class for CPU information."""

    cores: int | None = None
    percent: float = 0.0
    load_avg: tuple[float, float, float] | None = None


@dataclass(frozen=True)
class MirrorlistInfo:
    """Data class for pacman mirrorlist information."""

    total_mirrors: int = 0
    protocols: set[str] = field(default_factory=set)
    last_modified: str | None = None
