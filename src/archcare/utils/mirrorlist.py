"""
Mirrorlist utility functions for archcare.

Provides functions to manage and update pacman mirrorlists.
"""

from datetime import datetime
from pathlib import Path
from subprocess import CalledProcessError
from typing import Any

from loguru import logger

from .system import CommandResult, check_command_exists, run_command_with_sudo


def backup_file(source: Path, backup_suffix: str = ".backup") -> Path:
    """
    Create a backup of a file.

    Args:
        source: File to back up
        backup_suffix: Suffix for backup file

    Returns:
        Path to the backup file

    Raises:
        IOError: If backup fails
    """

    if not source.exists():
        raise IOError(f"Source file does not exist: {source}")

    # Create timestamped backup
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup_path = Path(f"{source}_{timestamp}{backup_suffix}")

    try:
        logger.debug(f"Creating backup: {source} -> {backup_path}")
        run_command_with_sudo(["cp", "-p", str(source), str(backup_path)], check=True)
    except CalledProcessError as e:
        logger.error(f"Failed to create backup: {e}")
        raise IOError(f"Could not create backup file: {e}")

    return backup_path


def restore_backup(backup_path: Path, target: Path) -> None:
    """
    Restore a file from backup.

    Args:
        backup_path: Backup file to restore from
        target: Target location to restore to

    Raises:
        IOError: If restore fails
    """

    if not backup_path.exists():
        raise IOError(f"Backup file does not exist: {backup_path}")

    try:
        logger.debug(f"Restoring backup: {backup_path} -> {target}")
        run_command_with_sudo(["cp", "-p", str(backup_path), str(target)], check=True)
    except CalledProcessError as e:
        logger.error(f"Failed to restore backup: {e}")
        raise IOError(f"Could not restore backup file: {e}")


def update_mirrorlist(
    country: str | list[str] | None = None,
    protocol: str | list[str] | None = None,
    latest: int = 20,
    number: int = 5,
    sort: str = "rate",
    save_path: Path | None = None,
) -> CommandResult:
    """
    Update mirrorlist using reflector.

    Args:
        country: Country or list of countries (e.g., "US" or ["US", "CA"])
        protocol: Protocol or list (e.g., "https" or ["https", "http"])
        latest: Number of most recently synchronized mirrors
        number: Maximum number of mirrors to include
        sort: Sort method (rate, age, country, score, delay)
        save_path: Where to save mirrorlist (None = stdout)

    Returns:
        CommandResult from reflector execution

    Raises:
        RuntimeError: If reflector command is not found
    """
    if not check_command_exists("reflector"):
        raise RuntimeError("'reflector' command not found")

    reflector_cmd = ["reflector"]

    # Add country filter
    if country:
        countries = country if isinstance(country, str) else ",".join(country)
        reflector_cmd.extend(["--country", countries])

    # Add protocol filter
    if protocol:
        protocols = protocol if isinstance(protocol, str) else ",".join(protocol)
        reflector_cmd.extend(["--protocol", protocols])

    # Add latest filter
    reflector_cmd.extend(["--latest", str(latest)])

    # Add number of mirrors
    reflector_cmd.extend(["--number", str(number)])

    # Add sort method
    reflector_cmd.extend(["--sort", sort])

    # Add save path if specified
    if save_path:
        reflector_cmd.extend(["--save", str(save_path)])

    logger.debug(f"Running reflector: {' '.join(reflector_cmd)}")

    return run_command_with_sudo(reflector_cmd, timeout=120)


def validate_mirrorlist(mirrorlist_path: Path) -> tuple[bool, str]:
    """
    Validate that a mirrorlist file is valid and has mirrors.

    Args:
        mirrorlist_path: Path to mirrorlist file

    Returns:
        Tuple of (is_valid: bool, message: str)
    """
    if not mirrorlist_path.exists():
        return False, f"Mirrorlist file does not exist: {mirrorlist_path}"

    try:
        content = mirrorlist_path.read_text()
    except Exception as e:
        return False, f"Could not read mirrorlist: {e}"

    # Check if file is empty
    if not content.strip():
        return False, "Mirrorlist is empty"

    # Count uncommented Server lines
    mirror_count = 0
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("Server = "):
            mirror_count += 1

    if mirror_count == 0:
        return False, "No valid mirror entries found"

    return True, f"Valid mirrorlist with {mirror_count} mirrors"


def get_mirrorlist_info(mirrorlist_path: Path) -> dict[str, Any]:
    """
    Get information about a mirrorlist file.

    Args:
        mirrorlist_path: Path to mirrorlist file

    Returns:
        Dictionary with mirrorlist info:
        - total_mirrors: Total number of mirror entries
        - protocols: Set of protocols found
        - last_modified: Last modification time
    """

    if not mirrorlist_path.exists():
        return {
            "total_mirrors": 0,
            "protocols": set(),
            "last_modified": None,
        }

    content = mirrorlist_path.read_text()

    # Count mirrors
    mirrors = []
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("Server = "):
            mirrors.append(line)

    # Extract protocols
    protocols = set()
    for mirror in mirrors:
        # Extract protocol (http, https, rsync)
        if "https://" in mirror:
            protocols.add("https")
        elif "http://" in mirror:
            protocols.add("http")
        elif "rsync://" in mirror:
            protocols.add("rsync")

    # Get last modified time
    last_modified = datetime.fromtimestamp(mirrorlist_path.stat().st_mtime).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    return {
        "total_mirrors": len(mirrors),
        "protocols": protocols,
        "last_modified": last_modified,
    }
