"""
Utility functions for archcare.
"""

from .hardware import get_cpu_info, get_disk_usage, get_memory_info
from .mirrorlist import (
    backup_file,
    get_mirrorlist_info,
    restore_backup,
    update_mirrorlist,
    validate_mirrorlist,
)
from .pacman import check_package_files, check_pacman_database
from .system import (
    change_ownership_to_user,
    check_command_exists,
    check_filesystem_errors,
    format_bytes,
    get_service_logs,
    get_service_status,
    get_system_uptime,
    get_systemd_failed_services,
    is_root,
    run_command,
    run_command_with_sudo,
    run_systemctl,
)

__all__ = [
    # Command execution
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
