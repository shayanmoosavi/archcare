"""
Pacman utility functions for archcare.

Provides convenient wrappers around pacman commands.
"""

from .system import check_command_exists, run_command, run_command_with_sudo


def check_pacman_database() -> tuple[bool, str]:
    """
    Check if pacman database is healthy.

    Returns:
        Tuple of (is_healthy: bool, message: str)
    """
    # Check if pacman is available
    if not check_command_exists("pacman"):
        return False, "pacman command not found"

    # Check the database integrity
    result = run_command(["pacman", "-Dk"])

    if not result.success:
        return False, f"Pacman database integrity check failed: {result.stderr}"

    return True, "Pacman database healthy"


def check_package_files() -> tuple[bool, str]:
    """
    Check for missing files in installed packages.

    Returns:
        Tuple of (all_files_present: bool, message: str)
    """
    # Check if pacman is available
    if not check_command_exists("pacman"):
        return False, "pacman command not found"

    # Check for missing files
    result = run_command_with_sudo(["pacman", "-Qk"])

    if not result.success:
        return False, f"Package file check failed: {result.stderr}"

    # Healthy installed package should have all the required files
    missing_files = [
        line for line in result.stdout.splitlines() if "0 missing files" not in line
    ]

    if missing_files:
        return False, "Missing files found:\n" + "\n".join(missing_files)

    return True, "All package files are present"
