"""Structured data models for return values of some utility functions."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceStatusInfo:
    """Data class for service status information."""

    loaded: bool = False
    active: str = "unknown"
    running: bool = False
    description: str = ""
    main_pid: int | None = None
