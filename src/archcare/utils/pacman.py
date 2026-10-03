"""
Pacman utility functions for archcare.

Provides convenient wrappers around pacman and pacman-contrib commands. Two groups live here:

- **Health check helpers** — used by `HealthCheckTask`. These are non-mutating checks that validate
    the integrity of the system package database and missing package files.
- **System update helpers** — used by `SystemUpdateTask` task. These are several convenient helper
    functions responsible for safely checking pending updates, backing up / restoring the sync
    database, running the system upgrade, and cleaning up pacman cache.

!!! note "Non-mutating vs. mutating"
    [`get_pending_repo_updates`][] is deliberately built on `checkupdates`, which works on a
    throwaway copy of the sync database and therefore never touches the real one. The mutating
    operations are called out as such in their own docstrings.

See Also:
    - [`HealthCheckTask`][archcare.tasks.health_check.HealthCheckTask]: Task that uses
        the health check helpers
    - [``SystemUpdateTask`][archcare.tasks.system_update.SystemUpdateTask]: Task that uses
        the system update helpers
    - [`archcare.utils.system_update`][]: AUR upgrade, Arch news, and snapshot helpers
    - [`archcare.utils.system`][]: Underlying command execution utilities
"""

from datetime import datetime
from pathlib import Path
from subprocess import CalledProcessError

from loguru import logger

from .info_models import PackageUpdateInfo
from .system import (
    CommandOptions,
    CommandResult,
    check_command_exists,
    run_command,
    run_command_with_sudo,
)

# Location of the pacman sync database, snapshotted before a system upgrade so an aborted
# transaction can be rewound to a state consistent with the installed packages.
SYNC_DB_PATH = Path("/var/lib/pacman/sync")


def check_pacman_database() -> tuple[bool, str]:
    """
    Check if pacman database is healthy.

    Validates the integrity of the local pacman database by running `pacman -Dk`. This checks for
    corrupted or missing database entries. Requires the `pacman` command to be available in `PATH`.

    Returns:
        (tuple[bool, str]): A tuple of `(is_healthy, message)`:

            - `is_healthy` (bool): True if database integrity check passes, False otherwise.
            - `message` (str): Descriptive message indicating success or failure reason.

    Raises:
        OSError: If the `pacman` command cannot be executed (e.g., not found, permission denied).

    See Also:
        [`check_package_files`][]: Complementary check for installed package file integrity
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

    Verifies that all files belonging to installed packages are present on disk by running
    `sudo pacman -Qk`. This requires sudo privileges to read all package files. Requires the
    `pacman` command to be available in `PATH`.

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
        [`check_pacman_database`][]: Complementary check for database integrity
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


def get_pending_repo_updates() -> list[PackageUpdateInfo]:
    """
    List pending official-repository updates without mutating the real sync database.

    Delegates to `checkupdates`, which points pacman at a throwaway copy of the sync database
    (under `TMPDIR`) so that querying pending updates never advances the system's own
    repositories. The output is passed through [`parse_pending_updates`][].

    Returns:
        (list[PackageUpdateInfo]): One entry per pending repository update, in the order
            `checkupdates` reported them. Empty when the system is up to date.

    Raises:
        OSError: If `checkupdates` fails for any reason other than "no updates available"
            (exit code 2, which is a normal empty result rather than an error).

    See Also:
        - [`parse_pending_updates`][]: The parser applied to the command output
        - [`archcare.utils.system_update.get_pending_aur_updates`][]: AUR equivalent
    """
    # `--nocolor` is required: when `Color` is enabled in pacman.conf, checkupdates emits ANSI
    # escapes that would corrupt the version fields.
    result = run_command(["checkupdates", "--nocolor"])

    if not result.success:
        raise OSError(f"checkupdates failed (exit {result.returncode}): {result.stderr}")

    updates = parse_pending_updates(result.stdout)
    logger.debug(f"Found {len(updates)} pending repository updates")
    return updates


def parse_pending_updates(stdout: str) -> list[PackageUpdateInfo]:
    """
    Parse pacman-style pending update output into structured entries.

    Both `checkupdates` and `paru -Qua` print one line per pending update as
    `name old_version -> new_version`. Lines that do not match that shape are skipped
    rather than raising, so stray banner or warning text on stdout cannot break the parse.

    Args:
        stdout (str): Raw standard output from an update query.

    Returns:
        (list[PackageUpdateInfo]): Parsed updates. Empty when no line matched.

    Examples:
        >>> from archcare.utils.pacman import parse_pending_updates
        >>> updates = parse_pending_updates("linux 6.10.1.arch1-1 -> 6.10.2.arch1-1")
        >>> updates[0].name
        'linux'
        >>> updates[0].new_version
        '6.10.2.arch1-1'
        >>> parse_pending_updates("some unexpected banner")
        []

    See Also:
        [`PackageUpdateInfo`][archcare.utils.info_models.PackageUpdateInfo]: The parsed shape
    """
    updates: list[PackageUpdateInfo] = []

    for line in stdout.splitlines():
        installed, separator, available = line.strip().partition(" -> ")
        if not separator:
            continue

        fields = installed.split()
        if len(fields) != 2:  # noqa: PLR2004 — exactly "name old_version"
            logger.debug(f"Skipping unrecognised update line: {line}")
            continue

        name, old_version = fields
        updates.append(
            PackageUpdateInfo(
                name=name,
                old_version=old_version,
                new_version=available.strip(),
            )
        )

    return updates


def is_package_installed(package: str) -> bool:
    """
    Check whether a package is installed using the pacman database.

    Args:
        package (str): Package name to look up.

    Returns:
        bool: `True` if `pacman -Qi <package>` succeeds. A missing package makes pacman exit
            non-zero, which `run_command` reports as `success=False`.
    """
    return run_command(["pacman", "-Qi", package]).success


def snapshot_package_manifest(destination: Path) -> Path:
    """
    Write the installed package manifest to a file.

    Captures `pacman -Q` (`name version` per line) into `destination`, creating parent
    directories as needed. Called once before and once after a system upgrade: diffing the two
    snapshots with [`diff_manifests`][] is how the task learns which packages the transaction
    removed, which cannot be recovered from the transaction's own output because the upgrade
    runs with stdio inherited.

    Args:
        destination (Path): File to write the manifest to. Overwritten if it exists.

    Returns:
        (Path): The `destination` that was written, returned for convenient chaining.

    Raises:
        OSError: If `pacman -Q` fails or the file cannot be written.

    Side Effects:
        Creates `destination` and any missing parent directories, and writes the manifest.

    See Also:
        [`diff_manifests`][]: Consumes two manifests produced here
    """
    result = run_command(["pacman", "-Q"])

    if not result.success:
        raise OSError(f"Failed to read the installed package manifest: {result.stderr}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(result.stdout + "\n", encoding="utf-8")

    logger.debug(
        f"Package manifest written to {destination} ({len(result.stdout.splitlines())} packages)"
    )
    return destination


def diff_manifests(before: Path, after: Path) -> list[str]:
    """
    Determine which packages disappeared between two manifests.

    Compares package *names* only (the first field of each manifest line), so a version change
    is never misreported as a removal. Explicitly removed packages, replaced packages, and
    packages dropped as orphaned dependencies all show up here.

    Args:
        before (Path): Manifest captured before the transaction, from
            [`snapshot_package_manifest`][].
        after (Path): Manifest captured after the transaction.

    Returns:
        (list[str]): Sorted names present in `before` but absent from `after`. Empty when
            nothing was removed.

    Raises:
        OSError: If either manifest cannot be read.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from archcare.utils.pacman import diff_manifests
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     before = Path(tmp) / "before"
        ...     after = Path(tmp) / "after"
        ...     _ = before.write_text("linux 6.1\\nexpat 2.0\\n")
        ...     _ = after.write_text("linux 6.2\\n")
        ...     diff_manifests(before, after)
        ['expat']

    See Also:
        [`snapshot_package_manifest`][]: Producer of the manifests
    """
    removed = _read_manifest_names(before) - _read_manifest_names(after)
    logger.debug(f"Detected {len(removed)} removed packages")
    return sorted(removed)


def _read_manifest_names(manifest: Path) -> set[str]:
    """
    Read the set of package names from a manifest file.

    Args:
        manifest (Path): Manifest written by `snapshot_package_manifest`.

    Returns:
        set[str]: Package names — the first whitespace-separated field of each line.

    Raises:
        OSError: If the manifest cannot be read.
    """
    names: set[str] = set()

    for line in manifest.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if fields:
            names.add(fields[0])

    return names


def backup_sync_db(destination_dir: Path) -> Path:
    """
    Copy the pacman sync database so an aborted transaction can be rewound.

    `pacman -Syu` refreshes the repository databases *before* it installs anything. If the
    install phase then fails partway, those databases describe a newer repository state than
    the packages actually installed, leaving the system inconsistent.

    Args:
        destination_dir (Path): Directory to place the timestamped backup in. Created if
            missing.

    Returns:
        Path: `<destination_dir>/sync-db_<YYYY-MM-DD_HHMMSS>` — the backup directory.

    Raises:
        OSError: If the sync database does not exist, or if the copy fails.

    Side Effects:
        Creates `destination_dir` and copies `SYNC_DB_PATH` into it with `cp -a`
        (recursive, preserving metadata). Runs through `sudo` for the copy.

    See Also:
        [`restore_sync_db`][]: The counterpart used during rollback
    """
    if not SYNC_DB_PATH.exists():
        raise OSError(f"Pacman sync database directory not found: {SYNC_DB_PATH}")

    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup_path = destination_dir / f"sync-db_{timestamp}"

    try:
        logger.debug(f"Backing up pacman sync database: {SYNC_DB_PATH} -> {backup_path}")
        run_command_with_sudo(
            ["cp", "-a", str(SYNC_DB_PATH), str(backup_path)],
            options=CommandOptions(check=True),
        )
    except CalledProcessError as e:
        logger.error(f"Failed to back up the pacman sync database: {e}")
        raise OSError(f"Could not back up the pacman sync database: {e}") from e

    logger.info(f"Pacman sync database backed up to {backup_path}")
    return backup_path


def restore_sync_db(backup: Path) -> None:
    """
    Restore the pacman sync database from a backup.

    Copies the backup's contents back over `SYNC_DB_PATH` as a merge rather than wiping
    the live directory first: a partial copy can then never leave the system with *no*
    repository databases at all.

    Args:
        backup (Path): Backup directory produced by [`backup_sync_db`][].

    Raises:
        OSError: If `backup` does not exist, or if the copy fails.

    Side Effects:
        Overwrites the repository databases under `SYNC_DB_PATH` with the backed-up
        versions. Runs through `sudo` for the copy.

    See Also:
        [`backup_sync_db`][]: Producer of the backup consumed here
    """
    if not backup.exists():
        raise OSError(f"Sync database backup does not exist: {backup}")

    try:
        logger.debug(f"Restoring pacman sync database: {backup} -> {SYNC_DB_PATH}")
        run_command_with_sudo(
            ["cp", "-a", f"{backup}/.", f"{SYNC_DB_PATH}/"],
            options=CommandOptions(check=True),
        )
    except CalledProcessError as e:
        logger.error(f"Failed to restore the pacman sync database: {e}")
        raise OSError(f"Could not restore the pacman sync database: {e}") from e

    logger.info("Pacman sync database restored from backup")


def run_system_upgrade() -> CommandResult:
    """
    Run a full official-repository system upgrade.

    Executes `pacman -Syu` through `sudo` with stdio deliberately *inherited*
    (`CommandOptions(capture_output=False)`), so pacman's own prompts, progress bars, and
    conflict/removal questions reach the real terminal. `--noconfirm` is intentionally **not**
    passed: pacman's native confirmation is the last checkpoint before changes are applied, and
    it is the only place pending package *removals* and conflicts become visible.

    Returns:
        CommandResult: Execution result. `stdout` and `stderr` are empty strings because the
            streams were not captured — inspect `success`/`returncode` instead.

    Side Effects:
        Performs the upgrade: refreshes the sync database, downloads packages, installs them,
        and updates `/var/lib/pacman/local`. Mutates the real system.

    See Also:
        - [`backup_sync_db`][]: Should be called before this
        - [`archcare.utils.system_update.run_aur_upgrade`][]: The AUR half of an update
    """
    logger.info("Running system upgrade: pacman -Syu")
    return run_command_with_sudo(
        ["pacman", "-Syu"],
        options=CommandOptions(capture_output=False),
    )


def clean_cache(
    keep: int,
    keep_uninstalled: int,
    cache_dir: Path = Path("/var/cache/pacman/pkg"),
) -> int:
    """
    Prune the pacman package cache with `paccache`.

    Runs two passes, because `paccache` applies a single `--keep` value per invocation:

    1. `paccache -r -k <keep>` — keeps `keep` recent versions of every *installed* package.
    2. `paccache -r -u -k <keep_uninstalled>` — keeps `keep_uninstalled` versions of every
       *uninstalled* package (the common `0` purges them outright).

    Best effort by design: failures are logged but never raised, because cache pruning runs
    after a successful upgrade and must not be able to fail the task.

    Args:
        keep (int): Versions to retain per installed package. Passed to `--keep`.
        keep_uninstalled (int): Versions to retain per uninstalled package.
        cache_dir (Path): Cache directory to prune. Passed explicitly via `-c` so this never
            depends on parsing `pacman.conf`. Defaults to `/var/cache/pacman/pkg`.

    Returns:
        int: Bytes reclaimed, derived from the cache directory's size before and after.
            `0` when nothing was removed or the directory is unreadable.

    Side Effects:
        Deletes cached package files under `cache_dir`. Runs through `sudo`.

    See Also:
        [`archcare.config.models.SystemUpdateSettings`][]: Source of the two retention values
    """
    before = _directory_size(cache_dir)
    cache_args = ["-c", str(cache_dir)]

    logger.info(f"Cleaning package cache: keep={keep}, keep_uninstalled={keep_uninstalled}")
    run_command_with_sudo(["paccache", "-r", "-k", str(keep), *cache_args])
    run_command_with_sudo(["paccache", "-r", "-u", "-k", str(keep_uninstalled), *cache_args])

    freed = max(before - _directory_size(cache_dir), 0)
    logger.info(f"Package cache cleanup reclaimed {freed} bytes")
    return freed


def _directory_size(path: Path) -> int:
    """
    Total size, in bytes, of all regular files under a directory.

    Args:
        path (Path): Directory to measure.

    Returns:
        int: Summed `st_size` of every regular file found recursively. `0` when the
            directory does not exist. Unreadable entries are skipped rather than raising, so
            a single permission problem cannot abort the measurement.
    """
    if not path.exists():
        return 0

    total = 0

    for entry in path.rglob("*"):
        try:
            if entry.is_file():
                total += entry.stat().st_size
        except OSError:
            logger.debug(f"Skipping unreadable cache entry: {entry}")

    return total


def list_pacnew_files() -> list[str]:
    """
    List `.pacnew` files awaiting manual review.

    Runs `pacdiff -o` (print-only mode; pacdiff never prompts or merges with this flag) and
    extracts the reported paths.

    Returns:
        (list[str]): Absolute paths of pending `.pacnew`/`.pacsave` files. Empty when there
            are none, or when `pacdiff` is unavailable or fails.

    See Also:
        [`archcare.core.task_details.SystemUpdateDetails`][]: Carries this list in its result
    """
    # `--nocolor` keeps ANSI escapes away from the paths, mirroring the update queries.
    result = run_command(["pacdiff", "-o", "--nocolor"])

    if not result.success:
        logger.warning(f"Could not check for .pacnew files: {result.stderr}")
        return []

    # pacdiff's exact separator is not documented. Splitting on any whitespace copes with both
    # newline- and space-separated output, and keeping only absolute paths guarantees stray
    # warning text can never be mistaken for a file.
    pacnew_files = [entry for entry in result.stdout.split() if entry.startswith("/")]
    logger.debug(f"Found {len(pacnew_files)} pending .pacnew files")
    return pacnew_files
