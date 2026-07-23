"""
Hardware utility functions for archcare.

Provides functions to query and manage hardware components.
"""

import os

import psutil
from loguru import logger

from .info_models import CpuInfo, DiskUsageInfo, MemoryInfo


def get_disk_usage(path: str = "/") -> DiskUsageInfo:
    """
    Get disk usage statistics for a path using psutil.

    Args:
        path: Path to check (default: root filesystem)

    Returns:
        DiskUsageInfo object with disk usage information
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
    Get system memory information using psutil.

    Returns:
        MemoryInfo object with memory information
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
    Get CPU usage information using psutil.

    Returns:
        CpuInfo object with CPU information
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
