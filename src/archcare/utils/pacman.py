"""
Pacman utility functions for archcare.

Provides convenient wrappers around pacman commands for system health checks.
This module is used by the [HealthCheckTask][archcare.tasks.health_check.HealthCheckTask]
to verify the integrity of the pacman database and installed package files.

Key Functions:
    - [check_pacman_database][]: Validates pacman database integrity via `pacman -Dk`
    - [check_package_files][]: Checks for missing files in installed packages via `pacman -Qk`

Both functions return a tuple of (success: bool, message: str) for consistent
error handling in the task execution pipeline.

See Also:
    - [HealthCheckTask][archcare.tasks.health_check.HealthCheckTask]: Task that uses these utilities
        for health checks
    - [archcare.utils.system][]: Underlying command execution utilities
"""

from .system import check_command_exists, run_command, run_command_with_sudo


def check_pacman_database() -> tuple[bool, str]:
    """
    Check if pacman database is healthy.

    Validates the integrity of the local pacman database by running `pacman -Dk`.
    This checks for corrupted or missing database entries. Requires the `pacman`
    command to be available in `PATH`.

    Returns:
        (tuple[bool, str]): A tuple of `(is_healthy, message)`:

            - `is_healthy` (bool): True if database integrity check passes, False otherwise.
            - `message` (str): Descriptive message indicating success or failure reason.

    Raises:
        OSError: If the `pacman` command cannot be executed (e.g., not found, permission denied).

    See Also:
        [check_package_files][]: Complementary check for installed package file integrity
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

    Verifies that all files belonging to installed packages are present on disk
    by running `sudo pacman -Qk`. This requires sudo privileges to read all package
    files. Requires the `pacman` command to be available in `PATH`.

    Warning: sudo priviledge
        This command requires sudo to function properly as some packages contain files
        in places owned by root.

    Returns:
        (tuple[bool, str]): A tuple of `(all_files_present, message)`:

            - `all_files_present` (bool): True if all package files are present, False if
                any missing.
            - `message` (str): Descriptive message listing missing files or confirming all present.

    Raises:
        OSError: If the `pacman` command cannot be executed or sudo fails.

    See Also:
        [check_pacman_database][]: Complementary check for database integrity
    """
    # Check if pacman is available
    if not check_command_exists("pacman"):
        return False, "pacman command not found"

    # Check for missing files
    result = run_command_with_sudo(["pacman", "-Qk"])

    if not result.success:
        return False, f"Package file check failed: {result.stderr}"

    # Healthy installed package should have all the required files
    missing_files = [line for line in result.stdout.splitlines() if "0 missing files" not in line]

    if missing_files:
        return False, "Missing files found:\n" + "\n".join(missing_files)

    return True, "All package files are present"
