"""
Pacman mirrorlist management utilities for Archcare.

Provides helpers to create timestamped backups of mirrorlist files, restore from backups, run
[reflector](https://wiki.archlinux.org/title/Reflector) to refresh the mirrorlist, validate the
resulting file, and parse its metadata.

All file operations use [`run_command_with_sudo`][] since the pacman mirrorlist (typically
`/etc/pacman.d/mirrorlist`) is root-owned. Callers are responsible for rollback logic; this module
focuses on atomic operations.

Configuration in ``settings.toml``:

```toml title="settings.toml"
[mirrorlist]
country = "Germany"
protocol = "https"
sort = "rate"
number_of_mirrors = 5
```

See Also:
    - [`MirrorlistInfo`][]: Structured mirrorlist metadata.
    - [`MirrorlistUpdateTask`][archcare.tasks.mirrorlist_update.MirrorlistUpdateTask]: Task
        composing these into a full update cycle.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from subprocess import CalledProcessError

from loguru import logger

from .info_models import MirrorlistInfo
from .system import CommandResult, check_command_exists, run_command_with_sudo


def backup_file(source: Path, backup_suffix: str = ".backup") -> Path:
    """
    Create a timestamped backup of a file.

    Copies the source file to `<source>_<YYYY-MM-DD_HHMMSS><backup_suffix>` using `cp -p` via
    [`run_command_with_sudo`][], preserving permissions and timestamps. This is used before
    mirrorlist updates so the original can be restored if the new mirrorlist is invalid.

    Args:
        source (Path): File to back up. Must exist on disk.
        backup_suffix (str): Suffix appended after the timestamp. Defaults to `".backup"`.

    Returns:
        Path: Absolute path to the newly created backup file.

    Raises:
        OSError: If the source file does not exist, or if the `cp` command fails (permissions,
            disk full, etc.).

    See Also:
        [`restore_backup`][]: Restoring a file from a backup created here.
    """

    if not source.exists():
        raise OSError(f"Source file does not exist: {source}")

    # Create timestamped backup
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup_path = Path(f"{source}_{timestamp}{backup_suffix}")

    try:
        logger.debug(f"Creating backup: {source} -> {backup_path}")
        run_command_with_sudo(["cp", "-p", str(source), str(backup_path)], check=True)
    except CalledProcessError as e:
        logger.error(f"Failed to create backup: {e}")
        raise OSError(f"Could not create backup file: {e}") from e

    return backup_path


def restore_backup(backup_path: Path, target: Path) -> None:
    """
    Restore a file from backup.

    Copies the backup file to the target path using `cp -p` via [`run_command_with_sudo`][],
    preserving permissions and timestamps. Typically called to roll back a failed mirrorlist update.

    Args:
        backup_path (Path): Backup file to restore from. Must exist.
        target (Path): Destination path to restore to. Parent directory must exist.

    Raises:
        OSError: If the backup file does not exist, or if the `cp` command fails.

    See Also:
        [`backup_file`][]: Creating a backup before an update.
    """

    if not backup_path.exists():
        raise OSError(f"Backup file does not exist: {backup_path}")

    try:
        logger.debug(f"Restoring backup: {backup_path} -> {target}")
        run_command_with_sudo(["cp", "-p", str(backup_path), str(target)], check=True)
    except CalledProcessError as e:
        logger.error(f"Failed to restore backup: {e}")
        raise OSError(f"Could not restore backup file: {e}") from e


@dataclass(frozen=True)
class ReflectorArgs:
    """
    Dataclass grouping all parameters for the reflector command.

    Attributes:
        country (str | list[str] | None): Optional country filter(s) passed to `--country`. Accepts
            a single country code (`"US"`) or a list (`["US", "CA"]`).
        protocol (str | list[str] | None): Optional protocol filter(s) passed to `--protocol`. Valid
            values include `"https"`, `"http"`, and `"rsync"`.
        latest (int): Only include this many latest synchronized mirrors. Passed to `--latest`.
            Defaults to `20`.
        number (int): Maximum number of mirrors in the output. Passed to `--number`.
            Defaults to `5`.
        sort (str): Sort method passed to `--sort`. Valid values: `"rate"`, `"age"`, `"country"`,
            `"score"`, and `"delay"`. Defaults to `"rate"`.
        save_path (Path | None): Destination for the generated mirrorlist. Passed to `--save`. When
            `None`, reflector writes to stdout. Defaults to `None`.
    """

    country: str | list[str] | None = None
    protocol: str | list[str] | None = None
    latest: int = 20
    number: int = 5
    sort: str = "rate"
    save_path: Path | None = None


def update_mirrorlist(
    payload: ReflectorArgs,
) -> CommandResult:
    """
    Refresh the pacman mirrorlist using reflector.

    Builds and executes a `reflector` command with the given filters, then returns the structured
    [`CommandResult`][]. The command is run via [`run_command_with_sudo`][] because the default
    target (typically `/etc/pacman.d/mirrorlist`) is root-owned.

    The total timeout scales with `latest`: `latest * 5 + 30` seconds, giving each mirror up to 5
    seconds plus a 30-second padding.

    Args:
        payload (ReflectorArgs): Reflector command parameters including country, protocol, latest,
            number, sort, and save path.

    Returns:
        CommandResult: Execution result from reflector, with stdout containing the mirrorlist when
            `save_path` is `None`.

    Raises:
        RuntimeError: If `reflector` is not installed on the system.

    See Also:
        [`validate_mirrorlist`][]: Validating the resulting file after this call.
    """
    if not check_command_exists("reflector"):
        raise RuntimeError("'reflector' command not found")

    reflector_cmd = ["reflector"]

    # Add country filter
    if payload.country:
        countries = (
            payload.country if isinstance(payload.country, str) else ",".join(payload.country)
        )
        reflector_cmd.extend(["--country", countries])

    # Add protocol filter
    if payload.protocol:
        protocols = (
            payload.protocol if isinstance(payload.protocol, str) else ",".join(payload.protocol)
        )
        reflector_cmd.extend(["--protocol", protocols])

    # Add latest filter
    reflector_cmd.extend(["--latest", str(payload.latest)])

    # Add number of mirrors
    reflector_cmd.extend(["--number", str(payload.number)])

    # Add sort method
    reflector_cmd.extend(["--sort", payload.sort])

    # Add save path if specified
    if payload.save_path:
        reflector_cmd.extend(["--save", str(payload.save_path)])

    logger.debug(f"Running reflector: {' '.join(reflector_cmd)}")

    # Total timeout for reflector command
    # Worst case scenario: all mirrors timeout (number_of_mirrors * download_timeout)
    # plus some padding
    # Default reflector timeout: 5 sec
    cmd_timeout = payload.latest * 5 + 30  # Add 30 seconds padding

    return run_command_with_sudo(reflector_cmd, timeout=cmd_timeout)


def validate_mirrorlist(mirrorlist_path: Path) -> tuple[bool, str]:
    """
    Validate that a mirrorlist file exists, is non-empty, and contains mirrors.

    Reads the file and counts uncommented `Server = ` lines. Returns a boolean status together with
    a human-readable message suitable for logging or display.

    Args:
        mirrorlist_path (Path): Path to the mirrorlist file to validate.

    Returns:
        (tuple[bool, str]): A pair of `(is_valid, message)`. `is_valid` is `True` when the file
            exists, is readable, and contains at least one `Server = ` line. `message` describes
            the result (e.g. `"Valid mirrorlist with 3 mirrors"` or an error reason).

    Examples:
        >>> from pathlib import Path
        >>> from tempfile import TemporaryDirectory
        >>> with TemporaryDirectory() as d:
        ...     path = Path(d) / "mirrorlist"
        ...     _ = path.write_text("Server = https://mirrors.example.com\\n")
        ...     valid, msg = validate_mirrorlist(path)
        ...     valid
        True

        >>> with TemporaryDirectory() as d:
        ...     path = Path(d) / "empty_mirrorlist"
        ...     path.touch()
        ...     validate_mirrorlist(path)
        (False, 'Mirrorlist is empty')

        >>> validate_mirrorlist(Path("/nonexistent/path"))
        (False, 'Mirrorlist file does not exist: /nonexistent/path')

    See Also:
        [`get_mirrorlist_info`][]: Richer metadata extraction for a valid file.
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
        stripped = line.strip()
        if stripped.startswith("Server = "):
            mirror_count += 1

    if mirror_count == 0:
        return False, "No valid mirror entries found"

    return True, f"Valid mirrorlist with {mirror_count} mirrors"


def get_mirrorlist_info(mirrorlist_path: Path) -> MirrorlistInfo:
    """
    Parse a mirrorlist file and return structured metadata.

    Extracts the total number of uncommented `Server = ` lines, the set of protocols in use
    (`https`, `http`, `rsync`), and the file's last modified timestamp.

    Args:
        mirrorlist_path (Path): Path to the mirrorlist file to parse.

    Returns:
        MirrorlistInfo: Parsed metadata. Returns a zero-initialized instance
            when the file does not exist.

    Examples:
        >>> from pathlib import Path
        >>> from tempfile import TemporaryDirectory
        >>> with TemporaryDirectory() as d:
        ...     path = Path(d) / "mirrorlist"
        ...     _ = path.write_text(
        ...         "Server = https://mirrors.example.com\\nServer = http://other.example.com\\n"
        ...     )
        ...     info = get_mirrorlist_info(path)
        ...     info.total_mirrors
        2
        >>> get_mirrorlist_info(Path("/nonexistent")).total_mirrors
        0

    See Also:
        [`validate_mirrorlist`][]: Lightweight validation without full parsing.
    """

    if not mirrorlist_path.exists():
        return MirrorlistInfo()

    content = mirrorlist_path.read_text()

    # Count mirrors
    mirrors = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("Server = "):
            mirrors.append(stripped)

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

    return MirrorlistInfo(
        total_mirrors=len(mirrors),
        protocols=protocols,
        last_modified=last_modified,
    )
