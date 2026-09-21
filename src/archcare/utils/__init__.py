"""
Provide shared system utility functions, subprocess wrappers, and terminal formatting helpers.

This package defines the system/OS boundary of Archcare. It acts as the utility and hardware-query
layer of the application, orchestrating low-level system calls, parsing raw OS output, and
formatting CLI presentations.

Modules:
    hardware: Query and monitor physical hardware metrics (CPU, disk, memory) via psutil.
    mirrorlist: Manage, backup, restore, update, and validate Arch Linux pacman mirrorlists.
    output: Emits beautifully formatted CLI console elements (panels, tables, status markers)
        using Rich.
    pacman: Run checkers to verify local pacman database and system package file integrity.
    system: Execute robust, timed subprocesses, systemctl service queries, and manage file
        permissions.

Public API:
    - [`run_command`][]: Run a system command and return a structured
        [`CommandResult`][archcare.utils.system.CommandResult].
    - [`run_command_with_sudo`][]: Run a command with sudo privileges if the current process is not
        running as root.
    - [`run_systemctl`][]: Execute a systemctl command with the specified arguments.
    - [`check_command_exists`][]: Check if a command is available in the system `PATH`.
    - [`is_root`][]: Check if the current process is running with root privileges.
    - [`change_ownership_to_user`][]: Change the owner and group ownership of a filesystem path to
        a specified user.
    - [`get_systemd_failed_services`][]: Retrieve a list of systemd units that are currently in
        a failed state.
    - [`get_service_status`][]: Retrieve comprehensive status information for a specified
        systemd service.
    - [`get_service_logs`][]: Retrieve the most recent log entries for a systemd service using
        journalctl.
    - [`is_valid_systemd_unit_name`][]: Validate if a given string constitutes a syntactically valid
        systemd unit name.
    - [`check_filesystem_errors`][]: Scan dmesg and system logs via journalctl for recent filesystem
        and hardware errors.
    - [`format_bytes`][]: Convert a raw byte count into a human-readable string representation
        with units.
    - [`get_system_uptime`][]: Retrieve the system's uptime formatted as a human-readable string.
    - [`get_disk_usage`][]: Get disk usage statistics for a specified filesystem path.
    - [`get_cpu_info`][]: Get detailed CPU usage information including utilization, cores,
        and load averages.
    - [`get_memory_info`][]: Get comprehensive system memory information including virtual
        and swap memory.
    - [`backup_file`][]: Create a timestamped backup of a file using sudo to ensure proper
        permissions.
    - [`restore_backup`][]: Restore a file from a backup to its original location using sudo.
    - [`update_mirrorlist`][]: Update the system mirrorlist using the reflector tool with
        customizable filters.
    - [`validate_mirrorlist`][]: Validate the structure and content of a mirrorlist file.
    - [`get_mirrorlist_info`][]: Extract detailed information from a mirrorlist file.
    - [`check_pacman_database`][]: Verify the health of the local pacman package database.
    - [`check_package_files`][]: Check system package file integrity using pacman.
    - [`configure_console`][]: Configure the global console instance for interactive or silent
        modes.
    - `console`: The global Rich Console instance (`rich.console.Console`).
    - [`print_error`][]: Print an error message prefixed with a cross symbol in bold red.
    - [`print_header`][]: Print a bold cyan section header with a matching underline.
    - [`print_info`][]: Print an informational message prefixed with an info icon in bold blue.
    - [`print_panel`][]: Print a bordered, rounded panel with a styled title.
    - [`print_success`][]: Print a success message prefixed with a checkmark symbol in bold green.
    - [`print_table`][]: Print a standardized, rounded data table.
    - [`print_warning`][]: Print a warning message prefixed with a warning icon in bold yellow.

See Also:
    - [`archcare.core`][]: Core execution layer containing base tasks and scheduling
    - [`archcare.config`][]: Application settings, logging configuration, and schema definitions
"""

from .hardware import get_cpu_info, get_disk_usage, get_memory_info
from .mirrorlist import (
    backup_file,
    get_mirrorlist_info,
    restore_backup,
    update_mirrorlist,
    validate_mirrorlist,
)
from .output import (
    configure_console,
    console,
    print_error,
    print_header,
    print_info,
    print_panel,
    print_success,
    print_table,
    print_warning,
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
    is_valid_systemd_unit_name,
    run_command,
    run_command_with_sudo,
    run_systemctl,
)

__all__ = [
    "backup_file",
    "change_ownership_to_user",
    "check_command_exists",
    "check_filesystem_errors",
    "check_package_files",
    "check_pacman_database",
    "configure_console",
    "console",
    "format_bytes",
    "get_cpu_info",
    "get_disk_usage",
    "get_memory_info",
    "get_mirrorlist_info",
    "get_service_logs",
    "get_service_status",
    "get_system_uptime",
    "get_systemd_failed_services",
    "is_root",
    "is_valid_systemd_unit_name",
    "print_error",
    "print_header",
    "print_info",
    "print_panel",
    "print_success",
    "print_table",
    "print_warning",
    "restore_backup",
    "run_command",
    "run_command_with_sudo",
    "run_systemctl",
    "update_mirrorlist",
    "validate_mirrorlist",
]
