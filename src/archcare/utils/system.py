"""
Provide system command utilities and wrappers for Archcare.

This module provides safe, robust, and well-logged wrappers around `subprocess` for executing
system-level commands, systemd/systemctl queries, journalctl log retrieval, file ownership
management, and system status queries.

Key Components:

- **Subprocess execution**: [`run_command`][] and [`run_command_with_sudo`][] provide safe,
    typed execution of shell commands.
- **Systemd interaction**: [`run_systemctl`][], [`get_systemd_failed_services`][],
    [`get_service_status`][], and [`get_service_logs`][] encapsulate interactions with
    systemd units.
- **System utilities**: [`format_bytes`][], [`get_system_uptime`][], [`change_ownership_to_user`][],
    and [`is_valid_systemd_unit_name`][] support logging, scheduling, and file permission
    operations.

All operations are wrapped with logging via Loguru and return strongly typed result objects (e.g.,
[`CommandResult`][]).

See Also:
    [`archcare.utils.hardware`][]: For hardware queries (disk, CPU, memory) via `psutil`
"""

import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from loguru import logger

from .info_models import ServiceStatusInfo

# Recognized systemd unit type suffixes:
# https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html
_VALID_UNIT_SUFFIXES = frozenset(
    {
        "service",
        "socket",
        "device",
        "mount",
        "automount",
        "swap",
        "target",
        "path",
        "timer",
        "slice",
        "scope",
    }
)

# Systemd unit names allow ASCII letters, digits, and : - _ . \
# (backslash covers escape sequences like \x2d, used when a character
# that can't appear literally - e.g. a literal '/' - needs encoding).
_ALLOWED_CHARS = re.compile(r"^[A-Za-z0-9:_.\\-]+$")

_MAX_UNIT_NAME_LENGTH = 255  # systemd's UNIT_NAME_MAX


@dataclass
class CommandResult:
    """
    Represent the result of a system command execution.

    This dataclass encapsulates the outcome of running a subprocess command,
    holding its command string, exit code, outputs, and success status.

    Attributes:
        command (str): The full command string that was executed.
        returncode (int): The exit code returned by the executed process.
        stdout (str): The trimmed standard output stream from the command execution.
        stderr (str): The trimmed standard error stream from the command execution.
        success (bool): Indicates whether the command completed successfully.

    Info: Exit code
        For `systemctl status` commands, an exit code of 3 (for loaded but
        inactive status) is treated as successful.

    Examples:
        >>> from archcare.utils.system import CommandResult
        >>> result = CommandResult("echo test", 0, "test", "", True)
        >>> result.success
        True
        >>> print(result)
        [SUCCESS] echo test
    """

    command: str
    returncode: int
    stdout: str
    stderr: str
    success: bool

    def __str__(self) -> str:
        """Human-readable representation."""
        status = "SUCCESS" if self.success else f"FAILED (exit {self.returncode})"
        return f"[{status}] {self.command}"


def run_command(
    command: list[str] | str,
    check: bool = False,
    capture_output: bool = True,
    text: bool = True,
    timeout: float | None = None,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> CommandResult:
    """
    Run a system command and return a structured execution result.

    Executes a command using Python's `subprocess.run`. It handles converting string commands to
    argument lists, captures output, monitors timeouts, and logs execution. It includes special
    exit-code handling for `systemctl status` queries (treating exit code 3 as successful).

    Args:
        command (list[str] | str): The command to run as a list of arguments or a single string.
        check (bool): If True, raises `subprocess.CalledProcessError` if the process exits
            with a non-zero exit code. Defaults to `False`.
        capture_output (bool): If True, captures standard output and standard error.
            Defaults to `True`.
        text (bool): If True, returns standard output and error as strings instead of bytes.
            Defaults to `True`.
        timeout (int | float | None): The maximum time in seconds the command is allowed
            to run before being killed. Defaults to `None`.
        cwd (Path | None): The working directory to set before executing the command.
            Defaults to `None`.
        env (dict[str, str] | None): Custom environment variables dictionary to pass to the process.
            Defaults to `None`.

    Returns:
        CommandResult: Object containing command string, exit code, captured outputs,
            and success status.

    Raises:
        subprocess.CalledProcessError: If `check=True` and the command exits with a non-zero code.
        subprocess.TimeoutExpired: If the command execution exceeds the specified `timeout`.

    Examples:
        >>> from archcare.utils.system import run_command
        >>> res = run_command("echo hello")
        >>> res.success
        True
        >>> res.stdout
        'hello'
    """
    # Convert string command to list if needed
    if isinstance(command, str):
        command_str = command
        command_list = command.split()
    else:
        command_str = " ".join(command)
        command_list = command

    logger.debug(f"Running command: {command_str}")

    try:
        result = subprocess.run(
            command_list,
            capture_output=capture_output,
            text=text,
            check=check,
            timeout=timeout,
            cwd=cwd,
            env=env,
        )

        cmd_result = CommandResult(
            command=command_str,
            returncode=result.returncode,
            stdout=result.stdout.strip() if result.stdout else "",
            stderr=result.stderr.strip() if result.stderr else "",
            success=(
                # Systemctl status returns an exit code of 3 for failed services
                result.returncode == 3 or result.returncode == 0
                if "systemctl" in command_str
                else result.returncode == 0
            ),
        )

        if cmd_result.success:
            logger.debug(f"Command succeeded: {command_str}")
        else:
            logger.warning(f"Command failed: {command_str} (exit {cmd_result.returncode})")
            logger.warning(f"ERROR: {cmd_result.stderr}")

        return cmd_result

    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed with exception: {e}")
        raise

    except subprocess.TimeoutExpired as e:
        logger.error(f"Command timed out: {e}")
        raise


def run_command_with_sudo(
    command: list[str] | str,
    check: bool = False,
    capture_output: bool = True,
    text: bool = True,
    timeout: int | None = None,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> CommandResult:
    """
    Run a command with sudo privileges if the current process is not running as root.

    Wraps [`run_command`][] by prepending `sudo` to the command arguments if the current
    effective user ID (EUID) is not 0 (root). If already running as root, the command
    is executed unmodified.

    Args:
        command (list[str] | str): The command to run as a list of arguments or a single string.
        check (bool): If True, raises `subprocess.CalledProcessError` on failure.
            Defaults to `False`.
        capture_output (bool): If True, captures stdout and stderr. Defaults to `True`.
        text (bool): If True, decodes outputs to strings. Defaults to `True`.
        timeout (int | None): Timeout limit in seconds. Defaults to `None`.
        cwd (Path | None): Working directory context. Defaults to `None`.
        env (dict[str, str] | None): Custom environment variables. Defaults to `None`.

    Returns:
        CommandResult: Structured result of the command execution.

    Raises:
        subprocess.CalledProcessError: If `check=True` and the command fails.
        subprocess.TimeoutExpired: If execution time exceeds the specified timeout.

    See Also:
        - [`run_command`][]: The wrapped command used by this utility.
        - [`is_root`][]: Used to determine if `sudo` prefixing is required.
    """
    # Convert string to list if needed
    command_list = command.split() if isinstance(command, str) else list(command)

    # Check if we're already root
    if not is_root():
        # Prepend sudo
        command_list = ["sudo", *command_list]

    # Run the command
    return run_command(
        command_list,
        check=check,
        capture_output=capture_output,
        text=text,
        timeout=timeout,
        cwd=cwd,
        env=env,
    )


def check_command_exists(command: str) -> bool:
    """
    Check if a command is available in the system `PATH`.

    Verifies whether an executable with the specified command name exists and is executable
    within any directory in the system's `PATH`.

    Args:
        command (str): Name of the executable to search for (e.g., "reflector" or "systemctl").

    Returns:
        bool: True if the command is found in `PATH`, False otherwise.

    Examples:
        >>> from archcare.utils.system import check_command_exists
        >>> check_command_exists("sh")
        True
        >>> check_command_exists("nonexistent_command_name")
        False
    """
    exists = shutil.which(command) is not None
    logger.debug(f"Command '{command}' exists: {exists}")
    return exists


def run_systemctl(
    args: list[str],
    check: bool = False,
    timeout: int = 30,
) -> CommandResult:
    """
    Execute a systemctl command with the specified arguments.

    Constructs and runs a command prefixing arguments with `systemctl`. This is a specific
    helper wrapper around [`run_command`][] to simplify systemd service manager queries.

    Args:
        args (list[str]): List of arguments to pass to `systemctl` (e.g.,
            `["list-units", "--failed"]`).
        check (bool): If True, raises `subprocess.CalledProcessError` on non-zero exit code.
            Defaults to `False`.
        timeout (int): Time limit in seconds for command execution. Defaults to 30.

    Returns:
        CommandResult: Structured result of the systemctl command execution.
    """
    command = ["systemctl", *args]
    return run_command(command, check=check, timeout=timeout)


def is_root() -> bool:
    """
    Check if the current process is running with root privileges.

    Determines root status by checking if the effective user ID (EUID) is 0.
    Many maintenance operations (e.g., updating mirrorlists or checking package file integrity)
    require root privileges.

    Returns:
        bool: True if running as root (UID 0), False otherwise.

    Examples:
        >>> from archcare.utils.system import is_root
        >>> isinstance(is_root(), bool)
        True
    """
    import os

    return os.geteuid() == 0


def get_systemd_failed_services() -> list[str]:
    """
    Retrieve a list of systemd units that are currently in a failed state.

    Queries systemd using `systemctl list-units --state=failed` and parses the output
    to extract the names of all failed services.

    Returns:
        list[str]: Names of systemd units in a failed state. Returns an empty list
            if the query fails or if no failed units are found.

    See Also:
        [`run_systemctl`][]: Used to query the systemd manager.
    """
    result = run_systemctl(["list-units", "--state=failed", "--no-pager", "--plain", "--no-legend"])

    if not result.success:
        logger.warning("Failed to get systemd failed services")
        return []

    # Parse output: each line is "UNIT LOAD ACTIVE SUB DESCRIPTION"
    failed_services = []
    for line in result.stdout.splitlines():
        if line.strip():
            # Split by whitespace and take first field
            parts = line.split()
            if parts:
                failed_services.append(parts[0])

    logger.debug(f"Found {len(failed_services)} failed services")
    return failed_services


def _parse_loaded_status(line: str) -> bool:
    """
    Parse the 'Loaded:' status line from a systemctl status output.

    Args:
        line (str): The line containing 'Loaded:' information from systemctl.

    Returns:
        bool: True if the service is successfully loaded, False otherwise.
    """
    return "could not be found." not in line


def _parse_active_status(line: str) -> tuple[str, bool]:
    """
    Parse the 'Active:' status line from a systemctl status output.

    Determines both the broad state name (e.g., "active", "inactive", "failed") and a boolean
    flag indicating if the unit is currently actively running.

    Args:
        line (str): The line containing 'Active:' information from systemctl.

    Returns:
        tuple[str, bool]: A tuple containing:
            - `active_state` (str): The broad active state (e.g., "active", "inactive",
                "failed", "unknown").
            - `is_running` (bool): True if the process is running, False otherwise.
    """

    # 'inactive' check should be before 'active' to avoid false positives
    if "inactive" in line:
        return "inactive", False
    if "active" in line:
        return "active", "running" in line
    if "failed" in line:
        return "failed", False

    return "unknown", False


def _parse_main_pid(line: str) -> int | None:
    """
    Parse the main process ID (PID) from a systemctl status line.

    Args:
        line (str): The line starting with 'Main PID:' or containing the PID details.

    Returns:
        int | None: The parsed process ID as an integer, or `None` if parsing fails.
    """
    parts = line.split()
    if len(parts) >= 3:
        try:
            return int(parts[2])
        except ValueError:
            logger.debug(f"Failed to parse PID from: {line}")
    return None


def _get_service_description(service_name: str) -> str:
    """
    Query systemctl to obtain the description text of a specific service.

    Args:
        service_name (str): The name of the systemd unit to query.

    Returns:
        str: Description text of the service, or an empty string if it cannot be found.
    """
    result = run_systemctl(["list-units", service_name, "--no-pager", "--plain", "--no-legend"])

    if not result.success or not result.stdout:
        return ""

    # Last part of the line is the description
    parts = result.stdout.split(maxsplit=4)
    return parts[4] if len(parts) >= 5 else ""


def get_service_status(service_name: str) -> ServiceStatusInfo:
    """
    Retrieve comprehensive status information for a specified systemd service.

    Executes `systemctl status` for the service and parses key details such as
    whether the service is loaded, active, running, its description, and its PID.

    Args:
        service_name (str): The name of the systemd service unit to check.

    Returns:
        ServiceStatusInfo: Data model containing detailed service status attributes.

    See Also:
        [`ServiceStatusInfo`][archcare.utils.info_models.ServiceStatusInfo]: Data model for
            service details.
    """
    result = run_systemctl(["status", service_name, "--no-pager"])

    loaded = False
    active = "unknown"
    running = False
    main_pid = None

    # Parse the status output line by line
    for line in result.stdout.splitlines():
        stripped = line.strip()

        if "Loaded:" in stripped:
            loaded = _parse_loaded_status(stripped)

        elif "Active:" in stripped:
            active_state, is_running = _parse_active_status(stripped)
            active = active_state
            running = is_running

        elif stripped.startswith("Main PID:"):
            main_pid = _parse_main_pid(stripped)

    # Get description separately
    description = _get_service_description(service_name)

    return ServiceStatusInfo(
        loaded=loaded,
        active=active,
        running=running,
        description=description,
        main_pid=main_pid,
    )


def get_service_logs(
    service_name: str,
    lines: int = 50,
    since: str | None = None,
) -> list[str]:
    """
    Retrieve the most recent log entries for a systemd service using journalctl.

    Args:
        service_name (str): Name of the systemd service to query logs for.
        lines (int): Number of recent log lines to retrieve. Defaults to 50.
        since (str | None): Time constraint string (e.g., "1 hour ago", "today", "yesterday").
            Defaults to `None`.

    Returns:
        (list[str]): List of log entries as strings. Returns an empty list on failure.

    See Also:
        [`run_command`][]: Used to execute the journalctl command.
    """
    cmd = ["journalctl", "-u", service_name, "-n", str(lines), "--no-pager"]

    if since:
        cmd.extend(["--since", since])

    result = run_command(cmd)

    if not result.success:
        logger.warning(f"Failed to get logs for {service_name}")
        return []

    return result.stdout.splitlines()


def check_filesystem_errors() -> list[str]:
    """
    Scan dmesg and system logs via journalctl for recent filesystem and hardware errors.

    Searches kernel messages using journalctl for common error indicators (e.g.,
    low-level disk warnings, ext4/btrfs/xfs integrity messages, I/O errors).

    Returns:
        (list[str]): Up to 10 most recent error/warning log entries. Returns an empty
            list if no issues are detected or query fails.
    """
    errors = []

    # Check dmesg for filesystem errors
    result = run_command(["journalctl", "-k", "-p", "err", "-n", "100", "--no-pager"])

    if result.success and result.stdout:
        # Look for common filesystem error keywords
        keywords = ["ext4", "btrfs", "xfs", "I/O error", "filesystem", "disk"]

        for line in result.stdout.splitlines():
            if any(keyword.lower() in line.lower() for keyword in keywords):
                errors.append(line.strip())

    # Limit to last 10 errors
    return errors[-10:] if errors else []


def format_bytes(bytes_value: float) -> str:
    """
    Convert a raw byte count into a human-readable string representation with units.

    Formats byte sizes into KB, MB, GB, TB, or PB values using a 1024-base scaling factor.

    Args:
        bytes_value (float): Raw size in bytes to be formatted. Must be non-negative.

    Returns:
        str: Format-completed human-readable size string (e.g., "1.50 GB", "512.00 B").

    Examples:
        >>> from archcare.utils.system import format_bytes
        >>> format_bytes(500)
        '500.00 B'
        >>> format_bytes(1536)
        '1.50 KB'
        >>> format_bytes(1024 * 1024 * 5)
        '5.00 MB'
    """
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_value < 1024.0:
            return f"{bytes_value:.2f} {unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.2f} PB"


def _get_boot_time() -> datetime:
    """
    Retrieve the system's boot time as a timestamp.

    Returns:
        datetime: A datetime object representing the time of last system boot, or
            the current time if query fails.
    """
    import psutil

    try:
        boot_timestamp = psutil.boot_time()
        return datetime.fromtimestamp(boot_timestamp)
    except Exception as e:
        logger.error(f"Failed to get boot time: {e}")
        return datetime.now()  # Fallback


def get_system_uptime() -> str:
    """
    Retrieve the system's uptime formatted as a human-readable string.

    Calculates the duration since the last system boot time and formats it into days,
    hours, and minutes.

    Returns:
        str: Human-readable uptime string (e.g., "5 days, 3 hours" or "2 hours" or "just now").
    """

    boot_time = _get_boot_time()
    uptime = datetime.now() - boot_time

    days = uptime.days
    hours = uptime.seconds // 3600
    minutes = (uptime.seconds % 3600) // 60

    parts = []
    if days > 0:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours > 0:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes > 0 and days == 0:  # Only show minutes if less than a day
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")

    return ", ".join(parts) if parts else "just now"


def change_ownership_to_user(path: Path, user: str) -> None:
    """
    Change the owner and group ownership of a filesystem path to a specified user.

    This function changes both the owner user ID (UID) and primary group ID (GID) of
    a file or directory to match those of the specified username. This is crucial when
    Archcare is running as root (e.g., via a systemd system timer) but needs to write
    or modify configuration or state files that should belong to a specific user.

    Args:
        path (Path): Path to the target file or directory. Must exist.
        user (str): Username to set as the owner. Must exist in the system user database.

    Note:
        Logs warnings if user is not found, or if permissions prevent changing ownership,
        but does not raise exceptions, ensuring calling workflows can continue gracefully.

    See also:
        [`UserContext.chown_if_root`][archcare.config.user.UserContext.chown_if_root]:
            Method that uses this utility.
    """
    import os
    import pwd

    try:
        # Get user's UID and GID
        user_info = pwd.getpwnam(user)
        uid = user_info.pw_uid
        gid = user_info.pw_gid

        # Change ownership
        os.chown(path, uid, gid)
        logger.debug(f"Changed ownership of {path} to {user}:{gid}")

    except KeyError:
        logger.warning(f"User '{user}' not found - cannot change ownership of {path}")
    except PermissionError:
        logger.warning(f"Permission denied when changing ownership of {path} to {user}")
    except Exception as e:
        logger.warning(f"Failed to change ownership of {path} to {user}: {e}")


def is_valid_systemd_unit_name(name: str) -> bool:
    """
    Validate if a given string constitutes a syntactically valid systemd unit name.

    Ensures the name adheres to systemd specifications:

    - Length must not exceed 255 characters.
    - Suffix must match a known unit type (e.g., `.service`, `.timer`, `.target`).
    - Base name must only contain valid systemd-allowed characters.
    - Supports template/instance syntax (e.g., `getty@tty1.service`).

    Args:
        name (str): The unit name string to validate.

    Returns:
        bool: True if the string is a valid systemd unit name, False otherwise.

    Examples:
        >>> from archcare.utils.system import is_valid_systemd_unit_name
        >>> is_valid_systemd_unit_name("sshd.service")
        True
        >>> is_valid_systemd_unit_name("getty@tty1.service")
        True
        >>> is_valid_systemd_unit_name("invalid")
        False
        >>> is_valid_systemd_unit_name("invalid.unknown")
        False
    """

    # Check basic structure: non-empty, within length limit, and contains a dot
    if not name or len(name) > _MAX_UNIT_NAME_LENGTH or "." not in name:
        return False

    # Extracting the base name (before the dot) and suffix (after the dot)
    base, _, suffix = name.rpartition(".")
    if suffix not in _VALID_UNIT_SUFFIXES or not base:
        return False

    # Extracting the template name (before the @) and instance (after the @)
    if "@" in base:
        template_name, _, instance = base.partition("@")
        if not template_name or not instance:
            return False
        # It must contain only allowed characters
        return bool(_ALLOWED_CHARS.match(template_name) and _ALLOWED_CHARS.match(instance))

    return bool(_ALLOWED_CHARS.match(base))
