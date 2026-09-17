"""
Structured hardware and service information models for Archcare utility queries.

This module provides frozen, lightweight dataclasses used to encapsulate system-level metrics,
service states, and pacman metadata retrieved by the low-level utilities library. By returning
structured objects rather than bare dictionaries or tuples, the codebase gains type safety,
clear auto-completions, and robust static checking.

Key Models:
    - [`ServiceStatusInfo`][]: Details concerning active/inactive states of systemd services.
    - [`DiskUsageInfo`][]: Disk usage statistics (total, used, percentage) for a mounted filesystem.
    - [`MemoryInfo`][]: Total and active physical and swap memory metrics.
    - [`CpuInfo`][]: CPU core counts, load averages, and active utilization levels.
    - [`MirrorlistInfo`][]: Parsed pacman mirror lists containing mirror counts, modification dates,
        and protocols.

See Also:
    - [`archcare.utils.hardware`][]: Low-level psutil hardware querying functions.
    - [`archcare.utils.system`][]: Low-level systemd service status queries.
    - [`archcare.utils.pacman`][]: Mirrorlist and pacman database inspection helpers.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ServiceStatusInfo:
    """
    Encapsulates state and configuration metrics of a systemd unit service.

    Attributes:
        loaded (bool): `True` if the service unit definition file is successfully parsed and
            loaded into systemd; `False` otherwise. Defaults to `False`.
        active (str): The high-level activation state from systemd (e.g., `'active'`, `'inactive'`,
            `'failed'`, `'activating'`). Defaults to `"unknown"`.
        running (bool): `True` if the underlying service process is currently executing;
            `False` otherwise. Defaults to `False`.
        description (str): Human-readable descriptive text parsed from the unit's definition.
            Defaults to empty string.
        main_pid (int | None): Process ID of the main executing service daemon, or `None` if
            the service is not running. Defaults to `None`.

    Examples:
        >>> from archcare.utils.info_models import ServiceStatusInfo
        >>> info = ServiceStatusInfo(
        ...     loaded=True,
        ...     active="active",
        ...     running=True,
        ...     description="System Logging Service",
        ...     main_pid=1234,
        ... )
        >>> info.running
        True
        >>> info.main_pid
        1234
    """

    loaded: bool = False
    active: str = "unknown"
    running: bool = False
    description: str = ""
    main_pid: int | None = None


@dataclass(frozen=True)
class DiskUsageInfo:
    """
    Represents usage metrics for a specific mounted storage volume path.

    Attributes:
        path (str): The mount point path on the system filesystem (e.g., `'/'`, `'/home'`).
            Defaults to `'/'`.
        total (int): The total capacity of the partition in bytes. Defaults to `0`.
        used (int): The amount of storage space in use in bytes. Defaults to `0`.
        free (int): The remaining unallocated space in bytes. Defaults to `0`.
        percent (float): The percentage utilization of the partition (range: `0.0` to `100.0`).
            Defaults to `0.0`.

    Examples:
        >>> from archcare.utils.info_models import DiskUsageInfo
        >>> info = DiskUsageInfo(path="/", total=1000000, used=250000, free=750000, percent=25.0)
        >>> info.percent
        25.0
        >>> info.free
        750000
    """

    path: str = "/"
    total: int = 0
    used: int = 0
    free: int = 0
    percent: float = 0.0


@dataclass(frozen=True)
class MemoryInfo:
    """
    Represents active usage statistics of physical memory (RAM) and swap space.

    Attributes:
        total (int): Total physical memory installed in bytes. Defaults to `0`.
        available (int): Physical memory readily available to launch new applications in bytes.
            Defaults to `0`.
        used (int): Active physical memory currently allocated in bytes. Defaults to `0`.
        percent (float): Percentage utilization of active RAM (range: `0.0` to `100.0`).
            Defaults to `0.0`.
        swap_total (int): Total size of configured swap space in bytes. Defaults to `0`.
        swap_used (int): Swap space currently in use in bytes. Defaults to `0`.
        swap_percent (float): Percentage utilization of active swap space (range: `0.0` to `100.0`).
            Defaults to `0.0`.

    Examples:
        >>> from archcare.utils.info_models import MemoryInfo
        >>> info = MemoryInfo(total=16000, available=8000, used=8000, percent=50.0)
        >>> info.percent
        50.0
        >>> info.available
        8000
    """

    total: int = 0
    available: int = 0
    used: int = 0
    percent: float = 0.0
    swap_total: int = 0
    swap_used: int = 0
    swap_percent: float = 0.0


@dataclass(frozen=True)
class CpuInfo:
    """
    Captures system-wide CPU configuration and dynamic load averages.

    Attributes:
        cores (int | None): Total number of logical execution processors/cores, or `None` if
            unresolved. Defaults to `None`.
        percent (float): Collective CPU utilization level percentage across all cores
            (range: `0.0` to `100.0`). Defaults to `0.0`.
        load_avg (tuple[float, float, float] | None): System load averages for the past 1, 5,
            and 15 minutes, respectively, or `None` if unresolved on the host platform.
            Defaults to `None`.

    Examples:
        >>> from archcare.utils.info_models import CpuInfo
        >>> info = CpuInfo(cores=8, percent=12.5, load_avg=(1.5, 0.8, 0.5))
        >>> info.cores
        8
        >>> info.load_avg
        (1.5, 0.8, 0.5)
    """

    cores: int | None = None
    percent: float = 0.0
    load_avg: tuple[float, float, float] | None = None


@dataclass(frozen=True)
class MirrorlistInfo:
    """
    Represents metadata parsed from a pacman repository mirror list file.

    Attributes:
        total_mirrors (int): The count of configured mirror servers parsed from the file.
            Defaults to `0`.
        protocols (set[str]): Unique protocols (e.g., `'https'`, `'http'`, `'rsync'`) supported
            by the listed mirrors. Defaults to an empty set.
        last_modified (str | None): Last modified date of the mirror list file, or `None` if
            unresolved. Defaults to `None`.

    Examples:
        >>> from archcare.utils.info_models import MirrorlistInfo
        >>> info = MirrorlistInfo(
        ...     total_mirrors=5,
        ...     protocols={"https", "http"},
        ...     last_modified="2025-08-25",
        ... )
        >>> info.total_mirrors
        5
        >>> "https" in info.protocols
        True
    """

    total_mirrors: int = 0
    protocols: set[str] = field(default_factory=set)
    last_modified: str | None = None
