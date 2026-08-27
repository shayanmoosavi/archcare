"""
Low-level hardware metrics collection for Archcare.

Provides psutil-based helpers to query disk, memory, and CPU statistics.
All functions return frozen dataclasses from [archcare.utils.info_models][]:
[DiskUsageInfo][], [MemoryInfo][], and [CpuInfo][].

Each function handles psutil failures gracefully by logging an error and
returning a zero-initialized instance of the corresponding dataclass, so
callers never need to catch exceptions.

See Also:
    - [archcare.utils.info_models][]: Structured return types for all queries.
    - [archcare.utils.system][]: Systemd/service-level queries.
    - [HealthCheckTask][archcare.tasks.health_check.HealthCheckTask]: Task that
        composes these into a health check.
"""

import os

import psutil
from loguru import logger

from .info_models import CpuInfo, DiskUsageInfo, MemoryInfo


def get_disk_usage(path: str = "/") -> DiskUsageInfo:
    """
    Get disk usage statistics for a filesystem mount point.

    Wraps `psutil.disk_usage` to return a structured [DiskUsageInfo][]
    instance with total, used, free bytes, and percentage utilization.

    Args:
        path (str): Mount point path to query (default: root filesystem `'/'`).

    Returns:
        DiskUsageInfo: Usage metrics for the specified path. On failure, returns
            a zero-initialized instance with only `path` populated.
    """

    try:
        usage = psutil.disk_usage(path)
        return DiskUsageInfo(
            path=path,
            total=usage.total,
            used=usage.used,
            free=usage.free,
            percent=usage.percent,
        )
    except Exception as e:
        logger.error(f"Failed to get disk usage for {path}: {e}")
        return DiskUsageInfo(path=path)


def get_memory_info() -> MemoryInfo:
    """
    Get system memory (RAM and swap) usage statistics.

    Wraps `psutil.virtual_memory` and `psutil.swap_memory` to return a
    structured [MemoryInfo][] instance with physical and swap memory metrics.

    Returns:
        MemoryInfo: Memory metrics including total/available/used bytes and
            percentages for both physical RAM and swap. On failure, returns a
            zero-initialized instance.
    """

    try:
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()

        return MemoryInfo(
            total=mem.total,
            available=mem.available,
            used=mem.used,
            percent=mem.percent,
            swap_total=swap.total,
            swap_used=swap.used,
            swap_percent=swap.percent,
        )
    except Exception as e:
        logger.error(f"Failed to get memory info: {e}")
        return MemoryInfo()


def get_cpu_info() -> CpuInfo:
    """
    Get CPU utilization and load average information.

    Wraps `psutil.cpu_percent`, `psutil.cpu_count`, and `os.getloadavg`
    to return a structured [CpuInfo][] instance. The CPU percent is measured
    over a 1-second interval.

    Returns:
        CpuInfo: CPU metrics including core count, utilization percentage,
            and 1/5/15-minute load averages. On failure, returns an instance
            with percent=0.0, cores=0, and load_avg=None.
    """

    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()

        load_avg = os.getloadavg()

        return CpuInfo(
            percent=cpu_percent,
            cores=cpu_count,
            load_avg=load_avg,
        )
    except Exception as e:
        logger.error(f"Failed to get CPU info: {e}")
        return CpuInfo(
            percent=0.0,
            cores=0,
            load_avg=None,
        )
