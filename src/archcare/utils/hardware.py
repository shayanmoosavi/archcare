"""
Hardware utility functions for archcare.

Provides functions to query and manage hardware components.
"""

from typing import Any
import os

import psutil
from loguru import logger


def get_disk_usage(path: str = "/") -> dict[str, Any]:
    """
    Get disk usage statistics for a path using psutil.

    Args:
        path: Path to check (default: root filesystem)

    Returns:
        Dictionary with disk usage information:
        - total: Total space in bytes
        - used: Used space in bytes
        - free: Free space in bytes
        - percent: Usage percentage
        - path: Path checked
    """

    try:
        usage = psutil.disk_usage(path)
        return {
            "path": path,
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "percent": usage.percent,
        }
    except Exception as e:
        logger.error(f"Failed to get disk usage for {path}: {e}")
        return {
            "path": path,
            "total": 0,
            "used": 0,
            "free": 0,
            "percent": 0.0,
        }


def get_memory_info() -> dict[str, Any]:
    """
    Get system memory information using psutil.

    Returns:
        Dictionary with memory information:
        - total: Total RAM in bytes
        - available: Available RAM in bytes
        - used: Used RAM in bytes
        - percent: Usage percentage
        - swap_total: Total swap in bytes
        - swap_used: Used swap in bytes
        - swap_percent: Swap usage percentage
    """

    try:
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()

        return {
            "total": mem.total,
            "available": mem.available,
            "used": mem.used,
            "percent": mem.percent,
            "swap_total": swap.total,
            "swap_used": swap.used,
            "swap_percent": swap.percent,
        }
    except Exception as e:
        logger.error(f"Failed to get memory info: {e}")
        return {
            "total": 0,
            "available": 0,
            "used": 0,
            "percent": 0.0,
            "swap_total": 0,
            "swap_used": 0,
            "swap_percent": 0.0,
        }


def get_cpu_info() -> dict[str, Any]:
    """
    Get CPU usage information using psutil.

    Returns:
        Dictionary with CPU information:
        - percent: Overall CPU usage percentage
        - count: Number of CPU cores
        - load_avg: Load averages (1, 5, 15 minutes)
    """

    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()

        load_avg = os.getloadavg()

        return {
            "percent": cpu_percent,
            "count": cpu_count,
            "load_avg": load_avg,
        }
    except Exception as e:
        logger.error(f"Failed to get CPU info: {e}")
        return {
            "percent": 0.0,
            "count": 0,
            "load_avg": None,
        }
