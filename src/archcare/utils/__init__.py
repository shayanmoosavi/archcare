"""
Utility functions for archcare.
"""

from .logging import get_task_logger, setup_logging, setup_task_logging
from .output import (
    confirm,
    console,
    create_progress,
    print_divider,
    print_error,
    print_header,
    print_info,
    print_schedule_table,
    print_success,
    print_summary_panel,
    print_task_details,
    print_task_result,
    print_warning,
)

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
    # Logging
    "setup_logging",
    "setup_task_logging",
    "get_task_logger",
    # Output
    "console",
    "print_success",
    "print_error",
    "print_warning",
    "print_info",
    "print_header",
    "print_task_result",
    "print_schedule_table",
    "print_task_details",
    "print_summary_panel",
    "print_divider",
    "confirm",
    "create_progress",
]
