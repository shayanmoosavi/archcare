"""
AUR upgrade, Arch news, Btrfs snapshot, and restore-script helpers for the `system-update` task.

Complements [`archcare.utils.pacman`][], which owns the official-repository half of a system
update. Everything here funnels through [`run_command`][archcare.utils.system.run_command] /
[`run_command_with_sudo`][archcare.utils.system.run_command_with_sudo], the project's documented
sole OS boundary.

!!! note "Root vs. non-root"
    `paru` refuses to run as root — AUR builds must not be performed with elevated privileges.
    [`run_aur_upgrade`][] therefore uses [`run_command`][archcare.utils.system.run_command]
    without `sudo`, unlike the `pacman` half.

See Also:
    - [`archcare.utils.pacman`][]: Official-repository update, manifest, and cache helpers
    - [`SystemUpdateDetails`][archcare.core.task_details.SystemUpdateDetails]: Details payload
        that carries this module's results
"""

import shlex
from pathlib import Path

from loguru import logger

from .info_models import PackageUpdateInfo
from .pacman import SYNC_DB_PATH, is_package_installed, parse_pending_updates
from .system import (
    CommandOptions,
    CommandResult,
    check_command_exists,
    run_command,
    run_command_with_sudo,
)

# Default pacman package cache. Same value as `clean_cache`'s default in utils/pacman.py; kept
# here as a single source for the restore script, which cannot import anything at run time.
_PACKAGE_CACHE_DIR = Path("/var/cache/pacman/pkg")

# Packages that together provide automatic snapshots around a pacman transaction and
# boot-menu access to them. `snap-pac` pulls in `snapper` and `btrfs-progs` itself.
SNAPSHOT_PACKAGES = ("snap-pac", "grub-btrfs")


def has_unread_arch_news() -> bool:
    """
    Report whether the user has unread Arch Linux news.

    Running `pacman -Syu` without reading the news is one of the most common ways to break an
    Arch install, so the `system-update` task gates on this before touching anything.

    The check is deliberately **read-only**, which rules out `informant check` — that command
    exits with the unread count but, when exactly one item is unread, also prints and *marks it
    as read*. Using it here would silently consume the user's news notification. Informant's own
    pacman hook has the same interrupt-and-mark behaviour, and since the `informant` package
    ships both the hook and this CLI, detecting one is equivalent to detecting the other; the
    task therefore gates on the CLI and leaves reading the news to the user.

    Fails *open*: when `informant` is absent or errors, this returns `False` rather than
    blocking an upgrade on an undeterminable state.

    Returns:
        bool: `True` only when `informant` positively reports unread items.

    See Also:
        [`archcare.utils.pacman.run_system_upgrade`][]: The step this gate protects
    """
    if not check_command_exists("informant"):
        logger.info("informant is not installed; cannot determine unread Arch news")
        return False

    result = run_command(["informant", "list", "--unread"])

    if not result.success:
        logger.warning(
            f"informant failed, assuming no unread news: {result.stderr or result.stdout}"
        )
        return False

    unread = bool(result.stdout.strip())
    logger.debug(f"Unread Arch news detected: {unread}")
    return unread


def get_pending_aur_updates() -> list[PackageUpdateInfo]:
    """
    List pending AUR package updates without installing anything.

    Runs `paru -Qua` and parses the pacman-style output with
    [`parse_pending_updates`][archcare.utils.pacman.parse_pending_updates].

    `paru -Qua` wraps `pacman -Qu`, which exits non-zero when there is nothing to upgrade and
    prints nothing at all. Empty output is therefore read as "no AUR updates" regardless of the
    exit code; any stderr is surfaced only as a diagnostic warning, because a failed AUR query
    must not block the official-repository half of the update.

    Returns:
        (list[PackageUpdateInfo]): One entry per pending AUR update. Empty when there are none
            or when the query could not produce any output.

    See Also:
        - [`archcare.utils.pacman.get_pending_repo_updates`][]: Repository equivalent
        - [`run_aur_upgrade`][]: The step that acts on this list
    """
    result = run_command(["paru", "-Qua"])

    updates = parse_pending_updates(result.stdout)
    if updates:
        logger.debug(f"Found {len(updates)} pending AUR updates")
        return updates

    if result.stderr:
        logger.warning(f"paru -Qua reported: {result.stderr}")
    logger.debug("No pending AUR updates")
    return []


def run_aur_upgrade() -> CommandResult:
    """
    Upgrade all installed AUR packages.

    Executes `paru -Sua` with stdio deliberately *inherited*
    (`CommandOptions(capture_output=False)`). This is required for more than parity with the
    pacman half: `paru` reviews each AUR package's diff before building it, which is an
    interactive prompt against the real terminal.

    Runs under the invoking user rather than through `sudo`, because `paru` refuses to build AUR
    packages as root.

    Returns:
        CommandResult: Execution result. `stdout` and `stderr` are empty strings because the
            streams were not captured — inspect `success`/`returncode` instead.

    Side Effects:
        Builds and installs AUR updates, mutating the real system.

    See Also:
        [`archcare.utils.pacman.run_system_upgrade`][]: The repository half of an update
    """
    logger.info("Running AUR upgrade: paru -Sua")
    return run_command(["paru", "-Sua"], options=CommandOptions(capture_output=False))


def detect_btrfs_snapshot_tooling() -> bool:
    """
    Report whether automatic pre/post snapshot tooling is available.

    Detects `snap-pac` (creates snapper pre/post snapshot pairs around pacman transactions) and
    `grub-btrfs` (exposes those snapshots in the boot menu). Presence is checked through the
    package database (`pacman -Qi`) rather than
    [`check_command_exists`][archcare.utils.system.check_command_exists], because neither package
    installs a standalone binary on `PATH` the way `reflector` or `paru` do.

    When this is `True` the caller can tell the user that a rollback point is being created
    automatically, and can query it afterwards with [`get_latest_snapshot_id`][].

    Returns:
        bool: `True` only when both packages are installed.

    See Also:
        [`get_latest_snapshot_id`][]: Querying the snapshot this tooling produces
    """
    if not check_command_exists("pacman"):
        logger.warning("pacman not available; cannot detect snapshot tooling")
        return False

    installed = all(is_package_installed(package) for package in SNAPSHOT_PACKAGES)
    logger.debug(f"Btrfs snapshot tooling detected: {installed}")
    return installed


def get_latest_snapshot_id(config: str = "root") -> int | None:
    """
    Find the newest `pre` snapshot number for a snapper config.

    This is the snapshot to hand to `snapper rollback` when an update succeeded but left the
    system broken: `snap-pac` creates a `pre` snapshot immediately before the transaction and a
    matching `post` one after it, so rolling back to the `pre` number undoes exactly the update.

    Uses snapper's machine-readable CSV mode (`--csvout` with `--columns number,type`) rather
    than its human-facing table, which is explicitly documented as unstable for scripts and
    decorates the active snapshot's number with a `*` (e.g. `1*`) — enough to break naive integer
    parsing.

    Args:
        config (str): Snapper configuration name to query. Defaults to `"root"`.

    Returns:
        (int | None): Highest `pre` snapshot number found, or `None` when there are no `pre`
            snapshots or the listing could not be read.

    See Also:
        [`detect_btrfs_snapshot_tooling`][]: Guard to call before relying on this
    """
    result = run_command_with_sudo(
        ["snapper", "--csvout", "-c", config, "list", "--columns", "number,type"]
    )

    if not result.success:
        logger.warning(f"Could not list snapper snapshots: {result.stderr}")
        return None

    pre_snapshots: list[int] = []

    for line in result.stdout.splitlines():
        number, separator, snapshot_type = line.partition(",")
        if not separator or snapshot_type.strip() != "pre":
            continue

        try:
            pre_snapshots.append(int(number.strip()))
        except ValueError:
            # The CSV header row ("number,type") lands here, as would any malformed line.
            logger.debug(f"Skipping unparseable snapper row: {line}")

    if not pre_snapshots:
        logger.debug(f"No pre snapshots found for snapper config '{config}'")
        return None

    return max(pre_snapshots)


def build_restore_script(
    sync_db_backup: Path,
    cache_dir: Path = _PACKAGE_CACHE_DIR,
    sync_db_target: Path = SYNC_DB_PATH,
) -> str:
    """
    Render the shell script that restores this system to its pre-upgrade state.

    Follows the ArchWiki's documented procedure for reinstalling every package while preserving
    installation reason — see
    [installation reason](https://wiki.archlinux.org/title/Installation_reason) and
    [reinstalling all packages](https://wiki.archlinux.org/title/Pacman/Tips_and_tricks#Reinstalling_all_packages)
    sections.

    Nothing is executed. The commands are printed and commented out; the user reads them and
    decides.

    Every interpolated path is `shlex.quote`d, because the backup path comes from a recovery
    record on disk rather than from this codebase.

    Args:
        sync_db_backup (Path): Backup directory from
            [`backup_sync_db`][archcare.utils.pacman.backup_sync_db]. Treated as a hard
            precondition: without it the script exits before doing anything.
        cache_dir (Path): Package cache directory. Named only in the header's note about the
            exact-version alternative for a single package.
        sync_db_target (Path): Live sync-database directory to restore into.

    Returns:
        str: The script body, ending in a newline.

    See Also:
        - [`RecoveryService`][archcare.services.recovery_service.RecoveryService]: Where this script
            is written
        - [`restore_sync_db`][archcare.utils.pacman.restore_sync_db]: The merge-not-wipe
            rationale behind step 1 in the built restore script
    """
    return _RESTORE_SCRIPT_TEMPLATE.format(
        sync_backup=shlex.quote(str(sync_db_backup)),
        sync_target=shlex.quote(str(sync_db_target)),
        cache=shlex.quote(str(cache_dir)),
    )


# Rendered by `build_restore_script`. Three things in here are load-bearing and must not be
# "cleaned up" by a later reader:
#
#   1. Every `pacman -S` line is COMMENTED OUT. This script exists to hand the user one large
#      transaction covering every package, kernel and glibc included; running it for them would
#      be the worst possible default. Nothing past the sync-database restore executes.
#
#   2. `set -euo pipefail` is what makes the single `cp -a` safe. Without it, a failed copy
#      falls through to the printed commands and the user restores against a sync database that
#      was never restored — which installs NEWER packages while looking like a rollback.
#
#   3. `sudo cp -a "$SYNC_BACKUP/." "$SYNC_TARGET/"` merges rather than wipes, mirroring
#      `restore_sync_db()` in utils/pacman.py: a partial copy must never leave the system with
#      no repository databases at all. Do not "tidy" it into `mv` or a `rm -rf` first.
_RESTORE_SCRIPT_TEMPLATE = """\
#!/usr/bin/env bash
# archcare: restore this system to its pre-upgrade state.
# Generated by `archcare task recover system-update`. Edit freely - it is not regenerated.
#
# Method: the ArchWiki's documented full-restore procedure, which preserves each
# package's installation reason (explicitly installed vs installed as a dependency).
# Marking every dependency explicit would change what orphan removal targets.
#   https://wiki.archlinux.org/title/Installation_reason
#   https://wiki.archlinux.org/title/Pacman/Tips_and_tricks#Reinstalling_all_packages
#
# Scope note: this restores VERSIONS, and only where the old version is still
# reachable. The commands below resolve from the sync database restored in step 1,
# so a package whose old version has since been rotated out of that database will
# NOT be downgraded. For a single package, an exact-version rollback is exact: install
# the cached artifact directly instead.
#   sudo pacman -U {cache}/<name>-<version>-<arch>.pkg.tar.zst
set -euo pipefail

SYNC_BACKUP={sync_backup}
SYNC_TARGET={sync_target}

# --- 0. Hard precondition -----------------------------------------------
# Without the pre-upgrade sync database the commands below would resolve to the
# CURRENT versions and reinstall them, which is not a restore at all.
if [ ! -d "$SYNC_BACKUP" ]; then
  echo "CRITICAL: sync database backup not found at $SYNC_BACKUP" >&2
  echo "The pre-upgrade dependency state is unrecoverable via archcare." >&2
  echo "Restore $SYNC_TARGET from your own backup before continuing." >&2
  exit 1
fi

# --- 1. Revert the sync database ---------------------------------------
# Merge, never wipe: a partial copy must not leave the system with no
# repository databases at all. Mirrors restore_sync_db() in utils/pacman.py.
echo "Restoring pacman sync database from $SYNC_BACKUP"
sudo cp -a "$SYNC_BACKUP/." "$SYNC_TARGET/"

# --- 2. The restore commands -------------------------------------------
# Native packages first, then foreign (AUR) ones. A separate command is required
# for the second half because -S resolves from the sync databases, and AUR packages
# are not in them.
#
# -Qe is the explicitly-installed set rather than every native package: the
# dependencies come back as dependencies of those, which is the correct semantic
# and a fraction of the pacman work.
#
# --needed is deliberately ABSENT: it would skip every package the restored
# databases still list as current, which is most of them.
echo
echo "Review each command below, then uncomment and run it."
echo
echo "# Native packages (preserves install reason):"
# pacman -Qe | sudo pacman -S -
echo
echo "# List of Foreign / AUR packages:"
# pacman -Qmq
"""
