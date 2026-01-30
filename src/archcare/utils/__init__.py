"""
Utility functions for archcare.
"""

from .logging import setup_logging, setup_task_logging
from .system import (
    CommandResult,
    check_command_exists,
    get_service_logs,
    get_service_status,
    get_systemd_failed_services,
    is_root,
    run_command,
    run_command_with_sudo,
    run_systemctl,
    check_filesystem_errors,
    format_bytes,
    get_system_uptime,
    change_ownership_to_user,
)
from .hardware import get_disk_usage, get_cpu_info, get_memory_info
from .mirrorlist import (
    backup_file,
    restore_backup,
    update_mirrorlist,
    validate_mirrorlist,
    get_mirrorlist_info,
)
from .pacman import check_pacman_database, check_package_files

__all__ = [
    # Command execution
    "CommandResult",
    "run_command",
    "run_command_with_sudo",
    "run_systemctl",
    "check_command_exists",
    # System checks
    "is_root",
    "change_ownership_to_user",
    # Systemd helpers
    "get_systemd_failed_services",
    "get_service_status",
    "get_service_logs",
    # Logging
    "setup_logging",
    "setup_task_logging",
    # System information
    "check_filesystem_errors",
    "format_bytes",
    "get_system_uptime",
    "get_disk_usage",
    "get_cpu_info",
    "get_memory_info",
    # Mirrorlist helpers
    "backup_file",
    "restore_backup",
    "update_mirrorlist",
    "validate_mirrorlist",
    "get_mirrorlist_info",
    # Pacman helpers
    "check_pacman_database",
    "check_package_files",
]
