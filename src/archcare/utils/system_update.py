"""
AUR upgrade, Arch news, and Btrfs snapshot helpers for the `system-update` task.

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

from loguru import logger

from .info_models import PackageUpdateInfo
from .pacman import is_package_installed, parse_pending_updates
from .system import (
    CommandOptions,
    CommandResult,
    check_command_exists,
    run_command,
    run_command_with_sudo,
)

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
