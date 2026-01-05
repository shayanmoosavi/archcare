"""
System command utilities for archcare.

Provides safe wrappers around subprocess for executing system commands.
"""

from datetime import datetime
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from loguru import logger


@dataclass
class CommandResult:
    """
    Result of a system command execution.
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
    timeout: int | None = None,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> CommandResult:
    """
    Run a system command and return structured result.

    Args:
        command: Command to run (list of args or string)
        check: Raise exception on non-zero exit code
        capture_output: Capture stdout/stderr
        text: Return output as string (vs bytes)
        timeout: Command timeout in seconds
        cwd: Working directory
        env: Environment variables

    Returns:
        CommandResult with execution details

    Raises:
        subprocess.CalledProcessError: If check=True and command fails
        subprocess.TimeoutExpired: If command exceeds timeout
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
            success=result.returncode == 0,
        )

        if cmd_result.success:
            logger.debug(f"Command succeeded: {command_str}")
        else:
            logger.warning(
                f"Command failed: {command_str} " f"(exit {cmd_result.returncode})"
            )

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
) -> CommandResult:
    """
    Run a command with sudo if not already root.

    Args:
        command: Command to run (list of args or string)
        check: Raise exception on non-zero exit code
        capture_output: Capture stdout/stderr
        text: Return output as string (vs bytes)
        timeout: Command timeout in seconds

    Returns:
        CommandResult with execution details

    Note:
    - If already root, runs command directly
    - If not root, prepends 'sudo' to command
    - User must be in sudoers and may be prompted for password
    """
    # Convert string to list if needed
    if isinstance(command, str):
        command_list = command.split()
    else:
        command_list = list(command)

    # Check if we're already root
    if not is_root():
        # Prepend sudo
        command_list = ["sudo"] + command_list

    # Run the command
    return run_command(
        command_list,
        check=check,
        capture_output=capture_output,
        text=text,
        timeout=timeout,
    )


def check_command_exists(command: str) -> bool:
    """
    Check if a command is available in PATH.

    Args:
        command: Command name to check

    Returns:
        True if command exists, False otherwise
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
    Run systemctl command.

    Args:
        args: Arguments to pass to systemctl
        check: Raise exception on failure
        timeout: Command timeout in seconds

    Returns:
        CommandResult from systemctl
    """
    command = ["systemctl"] + args
    return run_command(command, check=check, timeout=timeout)


def is_root() -> bool:
    """
    Check if running as root.

    Returns:
        True if running as root (UID 0)

    Reason:
    - Many maintenance tasks require root
    - Better to check explicitly than let commands fail
    """
    import os

    return os.geteuid() == 0


def get_systemd_failed_services() -> list[str]:
    """
    Get list of failed systemd services.

    Returns:
        List of service names that are in failed state
    """
    result = run_systemctl(
        ["list-units", "--state=failed", "--no-pager", "--plain", "--no-legend"]
    )

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
    Parse the 'Loaded:' line from systemctl status.

    Args:
        line: Line containing 'Loaded:' information

    Returns:
        True if service is loaded, False otherwise
    """
    return "not-found" not in line


def _parse_active_status(line: str) -> tuple[str, bool]:
    """
    Parse the 'Active:' line from systemctl status.

    Args:
        line: Line containing 'Active:' information

    Returns:
        Tuple of (active_state, is_running)

    Reason for extraction:
    - Reduces branching in main function
    - Clearer logic flow
    - Easy to extend with more states
    """

    if "active" in line:
        return "active", "running" in line
    elif "inactive" in line:
        return "inactive", False
    elif "failed" in line:
        return "failed", False

    return "unknown", False


def _parse_main_pid(line: str) -> int | None:
    """
    Parse the 'Main PID:' line from systemctl status.

    Args:
        line: Line containing 'Main PID:' information

    Returns:
        PID as integer, or None if parsing fails
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
    Get service description from systemctl list-units.

    Args:
        service_name: Name of the service

    Returns:
        Service description, or empty string if not found
    """
    result = run_systemctl(
        ["list-units", service_name, "--no-pager", "--plain", "--no-legend"]
    )

    if not result.success or not result.stdout:
        return ""

    # Last part of the line is the description
    parts = result.stdout.split(maxsplit=4)
    return parts[4] if len(parts) >= 5 else ""


def get_service_status(service_name: str) -> dict[str, Any]:
    """
    Get detailed status information for a service.

    Args:
        service_name: Name of the service

    Returns:
        Dictionary with service status information:
        - loaded: bool
        - active: str (active, inactive, failed, etc.)
        - running: bool
        - description: str
        - main_pid: int | None
    """
    result = run_systemctl(["status", service_name, "--no-pager"])

    status_info = {
        "loaded": False,
        "active": "unknown",
        "running": False,
        "description": "",
        "main_pid": None,
    }

    # Parse the status output line by line
    for line in result.stdout.splitlines():
        line = line.strip()

        if "Loaded:" in line:
            status_info["loaded"] = _parse_loaded_status(line)

        elif "Active:" in line:
            active_state, is_running = _parse_active_status(line)
            status_info["active"] = active_state
            status_info["running"] = is_running

        elif line.startswith("Main PID:"):
            status_info["main_pid"] = _parse_main_pid(line)

    # Get description separately
    status_info["description"] = _get_service_description(service_name)

    return status_info


def get_service_logs(
    service_name: str,
    lines: int = 50,
    since: str | None = None,
) -> list[str]:
    """
    Get recent logs for a service using journalctl.

    Args:
        service_name: Name of the service
        lines: Number of log lines to retrieve
        since: Time range (e.g., "1 hour ago", "today")

    Returns:
        List of log lines
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
    Check for filesystem errors in dmesg/journal.

    Returns:
        List of error messages found
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
    Format bytes as human-readable string.

    Args:
        bytes_value: Size in bytes

    Returns:
        Formatted string (e.g., "1.5 GB", "500 MB")
    """
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_value < 1024.0:
            return f"{bytes_value:.1f} {unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.2f} PB"


def _get_boot_time() -> datetime:
    """
    Get system boot time.

    Returns:
        Datetime of when system was booted
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
    Get system uptime as human-readable string.

    Returns:
        Uptime string (e.g., "5 days, 3 hours")
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
