"""
Utility functions for archcare.
"""

from .system import (
    CommandResult,
    check_command_exists,
    get_service_logs,
    get_service_status,
    get_systemd_failed_services,
    is_root,
    run_command,
    run_systemctl,
)

__all__ = [
    # Command execution
    "CommandResult",
    "run_command",
    "run_systemctl",
    "check_command_exists",
    # System checks
    "is_root",
    # Systemd helpers
    "get_systemd_failed_services",
    "get_service_status",
    "get_service_logs",
]
