"""
System update task implementation for Archcare.

This module provides `SystemUpdateTask`, a maintenance task that performs a full
`pacman -Syu` plus `paru -Sua` system upgrade with safety pre-flight checks and a two-tier
recovery story. It is intended to be registered in the static task registry and exposed to
users as the `system-update` command; that registration lands with the CLI wiring.

Workflow:
    1. `pre_check()` verifies that `pacman`, `paru`, and `checkupdates` are installed, that
        this process owns an interactive terminal, and that the user has no unread Arch news,
        a stale mirrorlist, or a pending kernel update requiring reboot.
    2. `should_run()` applies the `min_repo_updates_threshold` gate, so the system is only
        upgraded once enough packages are actually pending.
    3. `execute()` captures a pre-upgrade package manifest, backs up the pacman sync
        database, hands the terminal to `pacman -Syu` and then `paru -Sua`, captures a
        post-upgrade manifest, and diffs the two to report what was removed.
    4. If the transaction itself fails, the raised exception triggers
        [`BaseTask.rollback`][archcare.core.base_task.BaseTask.rollback], which restores the
        pacman sync database.
    5. `post_execute()` prunes the package cache on a *fully successful* outcome, and
        records the reclaimed byte count in the details payload.

!!! warning "Interactive by construction"
    Both the pacman and the AUR half run with stdio inherited so that pacman's native
    confirmation, conflict prompts, and paru's per-package diff review reach the real
    terminal. This task therefore refuses to run without a TTY (see `pre_check()`), and
    because it is a `TaskType.MANUAL` task it is never wired to a systemd timer.

!!! note "Metrics come from artifacts, not output"
    Since the streams are not captured, the transaction's own output cannot be parsed. The
    per-package lists in the returned details are therefore derived from the *pre-flight*
    update queries (which did capture output) plus a diff of the two package manifests
    captured around the transaction. See `execute()` for the exact rules.

Recovery:
    A record of the last run is written to
    [`AppSettings.recovery_dir`][archcare.config.models.AppSettings]/`system-update.json`,
    consumed by `archcare task recover system-update` (Phase 5). Nothing is restored
    automatically after a *successful* upgrade that left the system unhealthy.

See Also:
    - [`BaseTask`][]: Abstract workflow this task implements
    - [`TaskResult`][]: The structured result object that the task returns
    - [`SystemUpdateDetails`][]: Details schema produced by this task
    - [`archcare.utils.pacman`][]: Repository update, manifest, and cache utilities
    - [`archcare.utils.system_update`][]: AUR, Arch news, and snapshot utilities
"""

import dataclasses
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from archcare.config import SkipReason, TaskStatus
from archcare.core import (
    BaseTask,
    SystemUpdateDetails,
    TaskResult,
    TaskStep,
    failed,
    partial,
    success,
)
from archcare.utils import (
    PackageUpdateInfo,
    backup_sync_db,
    check_command_exists,
    clean_cache,
    detect_btrfs_snapshot_tooling,
    diff_manifests,
    fetch_arch_news_headlines,
    format_bytes,
    get_latest_snapshot_id,
    get_pending_aur_updates,
    get_pending_repo_updates,
    has_interactive_terminal,
    has_unread_arch_news,
    list_pacnew_files,
    restore_sync_db,
    run_aur_upgrade,
    run_command,
    run_system_upgrade,
    snapshot_package_manifest,
)
from archcare.utils.mirrorlist import get_mirrorlist_info
from archcare.utils.system import CommandOptions


class SystemUpdateTask(BaseTask):
    """
    Perform a full pacman + AUR system upgrade with pre-flight checks and rollback safety.

    The task backs up the pacman sync database, hands the terminal to `pacman -Syu` and
    `paru -Sua`, records what the transaction actually changed, prunes the package cache,
    and rolls the sync database back if the transaction itself fails.

    This task follows the [`BaseTask`][] Template Method contract:

    - `pre_check()`: requires `pacman`, `paru`, and `checkupdates`, an attached terminal,
        no unread Arch news, a fresh mirrorlist, and no pending kernel update (reboot)
    - `should_run()`: requires at least `min_repo_updates_threshold` pending repo updates
    - `execute()`: manifest -> sync-db backup -> pacman -> snapshot id -> AUR -> manifest ->
        diff -> pacnew -> recovery record
    - `post_execute()`: `paccache` cleanup on a fully successful outcome, plus a desktop
        notification on any terminal outcome
    - `rollback()`: restore the pacman sync database (invoked automatically by
        [`BaseTask.run`][] when `execute()` raises)

    Attributes:
        sync_db_backup (Path | None): Location of the pacman sync database backup created in
            `execute()`. May be pre-set via the constructor to exercise `rollback()` in
            isolation. `None` until a backup exists. Consumed by `rollback()`.
        pre_update_snapshot_id (int | None): Snapper `pre` snapshot number for this
            transaction, when Btrfs snapshot tooling is installed. `None` otherwise.
        manifest_before (Path | None): Package manifest captured before the transaction.
    """

    #: Number of discrete progress steps in `execute()`. The transaction is long-running but
    #: its phases are well-defined, so a determinate bar is used (contrast
    #: `MirrorlistUpdateTask`, which is spinner-only because reflector's phases are opaque).
    _STEP_COUNT = 9

    def __init__(self, sync_db_backup: Path | None = None, *args, **kwargs):
        """
        Initialize the system update task.

        Args:
            sync_db_backup (Path | None): Optional pre-existing sync database backup to use
                instead of creating one. Primarily useful for testing `rollback()`. Defaults
                to `None` (a timestamped backup is created in `execute()`).

        Other Args:
            *args (tuple): Forwarded to `BaseTask.__init__()` (`config`, `settings`, ...).
            **kwargs (dict): Forwarded to `BaseTask.__init__()`.

        Side Effects:
            Initializes the transaction bookkeeping attributes.
        """
        super().__init__(*args, **kwargs)
        self.sync_db_backup = sync_db_backup
        self.pre_update_snapshot_id: int | None = None
        self.manifest_before: Path | None = None
        self._pending_repo: list[PackageUpdateInfo] | None = None

    @property
    def recovery_file(self) -> Path:
        """
        Path of the recovery record written at the end of a successful upgrade.

        Returns:
            Path: `<recovery_dir>/system-update.json`.
        """
        return self.settings.recovery_dir / "system-update.json"

    def _pending_repo_updates(self) -> list[PackageUpdateInfo]:
        """
        Get pending repository updates, querying at most once per invocation.

        `should_run()` and `execute()` both need this list, and each call to `checkupdates`
        refreshes repository metadata over the network. Caching keeps the task to a single
        query while still letting `execute()` be exercised in isolation in tests.

        Returns:
            list[PackageUpdateInfo]: The cached list, querying on first access.

        Raises:
            OSError: Propagated from `get_pending_repo_updates()` if `checkupdates` fails.
                In `should_run()` this surfaces through `BaseTask.run()` as a task failure,
                which is the honest outcome: without a working update query the task cannot
                know whether there is work to do.
        """
        if self._pending_repo is None:
            with self.progress.spinner("Checking for pending repository updates..."):
                self._pending_repo = get_pending_repo_updates()
        return self._pending_repo

    def _should_skip_prompt(self) -> bool:
        """Return True if we already prompted for news acknowledgement recently."""
        if self.state is None:
            return False
        state = self.state.tasks.get(self.name)
        if state is None or state.last_news_prompt is None:
            return False
        window_seconds = self.settings.system_update.news_acknowledge_cooldown_minutes * 60
        return (datetime.now() - state.last_news_prompt).total_seconds() < window_seconds

    def _present_news_prompt(self) -> bool:
        """Show the news acknowledgement prompt and return the user's answer."""
        headlines = fetch_arch_news_headlines()
        if headlines:
            preview = "\n    - ".join(headlines)
            prompt = (
                f"There are unread Arch Linux news item(s), including:\n\n"
                f"    - {preview}\n\n"
                f"Read them before updating (`sudo informant read`, or `paru -Pw` if informant "
                f"can't be found), or visit https://archlinux.org/news/. Some updates require "
                f"manual intervention.\n\n"
                f"Proceed with the system update anyway?"
            )
        else:
            prompt = (
                "There are unread Arch Linux news items. Read them before updating "
                "(`sudo informant read`, or `paru -Pw` if informant can't be found), or visit "
                "https://archlinux.org/news/. Some updates require manual intervention.\n\n"
                "Proceed with the system update anyway?"
            )
        return self.interaction.confirm(prompt)

    def _record_news_prompt(self) -> None:
        """Persist the timestamp of the prompt that was just shown."""
        if self.state is not None:
            self.state.set_task_news_prompt(self.name)

    def _handle_unread_news_prompt(self) -> tuple[bool, str, SkipReason | None]:
        """
        Check for unread Arch news and, if the acknowledgement prompt is due, ask the user.

        Returns:
            (proceed, reason, skip_reason):
              - (True, "", None)    -> proceed: no news,
                                     acknowledged, no tool, or in cooldown
              - (False, reason, USER_CANCELLED) -> user declined
        """
        if not has_unread_arch_news():
            return True, "", None
        if self._should_skip_prompt():
            # Still within the acknowledgement window: don't nag again, let the user proceed.
            return True, "", None
        if self._present_news_prompt():
            self._record_news_prompt()
            return True, "", None
        # Timestamp recorded as soon as the prompt is shown — whether the user accepts or declines,
        # so the cooldown prevents nagging again within the acknowledgement window either way.
        self._record_news_prompt()
        return (
            False,
            (
                "Unread Arch Linux news — you declined to proceed. Read the news with "
                "`sudo informant read` (or `paru -Pw`) or at https://archlinux.org/news/ "
                "and re-run when ready."
            ),
            SkipReason.USER_CANCELLED,
        )

    def pre_check(self) -> tuple[bool, str]:
        """
        Verify prerequisites for the system update.

        Four classes of precondition, each with an actionable message:

        1. Required commands — `pacman`, `paru`, and `checkupdates` (from `pacman-contrib`).
        2. An attached interactive terminal — both transaction halves inherit stdio, so
           without a TTY pacman's confirmation and paru's diff review have nowhere to render.
        3. A fresh mirrorlist — stale mirrors cause download and upgrade failures.
        4. No pending kernel update — upgrading the running kernel in place can corrupt
           modules and leave the system unbootable; a reboot is required first.

        Returns:
            (tuple[bool, str]): A tuple of:

                - `can_run` (`bool`): `True` if all prerequisites are satisfied.
                - `reason` (`str`): The blocking explanation, or an empty string on success.

        Note:
            `BaseTask.run()` classifies any `pre_check()` failure as `SkipReason.DEPENDENCY_FAILED`;
            the skip reason is therefore generic for the terminal case and the message text is
            what actually tells the user what to do.

        See also:
            [`SkipReason`][archcare.config.enums.SkipReason]: The skip reason enum.
        """

        # A missing `pacman` is an extremely serious issue; hard fail.
        if not check_command_exists("pacman"):
            reason = (
                "`pacman` not found. What have you done? 💀\n"
                "Follow this guide in Arch wiki to manually re-install it:\n"
                "https://wiki.archlinux.org/title/Pacman#Manually_reinstalling_pacman"
            )

        # Paru is needed for AUR updates.
        elif not check_command_exists("paru"):
            reason = (
                "'paru' not found. Build and install it from the AUR:\n"
                "    sudo pacman -S --needed base-devel\n"
                "    git clone https://aur.archlinux.org/paru.git\n"
                "    cd paru && makepkg -si\n"
                "(or use another AUR helper, e.g. `yay -S paru`). "
                "See https://wiki.archlinux.org/title/Paru"
            )

        # `pacman-contrib` is needed for `checkupdates`.
        elif not check_command_exists("checkupdates"):
            reason = "'checkupdates' command not found. Install with: sudo pacman -S pacman-contrib"

        # Updates must be run interactively and sometimes need manual intervention, it's not safe
        # to update Arch Linux unattended.
        elif not has_interactive_terminal():
            reason = (
                "system-update needs an interactive terminal: pacman and paru must be able "
                "to show confirmations and conflicts. Run it directly from a shell, not from "
                "a pipe, a script, or a systemd timer."
            )

        else:
            reason = self._has_stale_mirrorlist() or self._requires_reboot()

        if reason:
            return False, reason
        return True, reason

    def _has_stale_mirrorlist(self) -> str:
        """
        Check if mirrorlist is stale.

        Returns:
            str: Helpful message if the mirrorlist is stale, or an empty string if the
                mirrorlist is not stale.
        """
        # A stale mirrorlist is a common source of errors and slow / failing downloads.
        info = get_mirrorlist_info(self.settings.mirrorlist.path)
        if info.last_modified is not None:
            STALE_THRESHOLD = 7
            mtime = datetime.strptime(info.last_modified, "%Y-%m-%d %H:%M:%S")
            if (datetime.now() - mtime).days > STALE_THRESHOLD:
                return (
                    f"Mirrorlist ({self.settings.mirrorlist.path}) is "
                    f"older than {STALE_THRESHOLD} days; "
                    "run `archcare task run mirrorlist-update` first."
                )
        return ""

    def _requires_reboot(self) -> str:
        """
        Check if a reboot is pending due to a kernel update.

        Compares the currently loaded kernel version (from `uname -r`)
        against the installed kernel package version. If the installed
        version is newer, a reboot is required.

        Returns:
            str: A message indicating if a reboot is pending, or an empty
                string if no reboot is required.
        """
        loaded_kernel = self._get_loaded_kernel()
        if not loaded_kernel:
            return ""

        pkg_name = self._get_kernel_package_owner(loaded_kernel)
        if not pkg_name:
            return ""

        installed_ver = self._get_installed_package_version(pkg_name)
        if not installed_ver:
            return ""

        if self._is_reboot_required(loaded_kernel, installed_ver):
            return (
                f"Pending reboot: loaded {loaded_kernel} but "
                f"{pkg_name} {installed_ver} is installed."
            )

        return ""

    def _get_loaded_kernel(self) -> str:
        """Get the currently loaded kernel version from `uname -r`."""
        loaded_res = run_command(["uname", "-r"], options=CommandOptions(check=False))
        return loaded_res.stdout.strip() if loaded_res.success else ""

    def _get_kernel_package_owner(self, loaded_kernel: str) -> str | None:
        """Find the package that owns the loaded kernel's modules directory."""
        owner_res = run_command(
            ["pacman", "-Qo", f"/usr/lib/modules/{loaded_kernel}"],
            options=CommandOptions(check=False),
        )
        if not owner_res.success:
            return None
        # Example output format: "/usr/lib/modules/6.9.1-arch1-1 is owned by linux 6.9.1.arch1-1"
        # We need the package name (5th token after splitting: file, is, owned, by, pkg, ver)
        parts = owner_res.stdout.strip().split()
        PKG_NAME_INDEX = 4
        MIN_PARTS = 5
        return parts[PKG_NAME_INDEX] if len(parts) >= MIN_PARTS else None

    def _get_installed_package_version(self, pkg_name: str) -> str | None:
        """Get the installed version of a package."""
        pkg_res = run_command(["pacman", "-Q", pkg_name], options=CommandOptions(check=False))
        if not pkg_res.success:
            return None
        parts = pkg_res.stdout.strip().split()
        VERSION_INDEX = 1
        MIN_PARTS = 2
        return parts[VERSION_INDEX] if len(parts) >= MIN_PARTS else None

    def _is_reboot_required(self, loaded_kernel: str, installed_ver: str) -> bool:
        """Check if installed kernel version is newer than loaded kernel."""
        load_clean = self._clean_kernel_version(loaded_kernel)
        try:
            # Parse both versions into comparable tuples
            installed_tuple = self._parse_kernel_version(installed_ver)
            load_tuple = self._parse_kernel_version(load_clean)
            return installed_tuple > load_tuple
        except Exception:
            return False

    def _parse_kernel_version(self, version: str) -> tuple[int, ...]:
        """
        Parse Arch kernel version into a comparable tuple.

        Arch kernel versions have two formats:
        - linux/linux-zen: X.Y.Z.flavorN-P  (e.g., 7.2.8.arch1-2, 7.2.9.zen1-1)
        - linux-lts: X.Y.Z-P                (e.g., 6.18.55-1)

        Returns tuple: (major, minor, patch, flavor_ver, pkgrel)
        where flavor_ver=0 for linux-lts (no flavor version)
        """
        KERNEL_VERSION_TUPLE_SIZE = 5
        DOT_COUNT_LTS = 2
        DASH_COUNT_LTS = 1

        # linux-lts: 6.18.55-1 -> (6, 18, 55, 0, 1)
        if version.count(".") == DOT_COUNT_LTS and version.count("-") == DASH_COUNT_LTS:
            base, pkgrel = version.rsplit("-", 1)
            major, minor, patch = map(int, base.split("."))
            return (major, minor, patch, 0, int(pkgrel))

        # linux: 7.2.8.arch1-2 -> (7, 2, 8, 1, 2)
        # linux-zen: 7.2.9.zen1-1 -> (7, 2, 9, 1, 1)
        if ".arch" in version or ".zen" in version:
            # Split on last "-" to get pkgrel
            base, pkgrel = version.rsplit("-", 1)
            # base is like "7.2.8.arch1" or "7.2.9.zen1"
            # Split on ".arch" or ".zen"
            if ".arch" in base:
                upstream, flavor_ver = base.split(".arch")
            else:
                upstream, flavor_ver = base.split(".zen")
            major, minor, patch = map(int, upstream.split("."))
            return (major, minor, patch, int(flavor_ver), int(pkgrel))

        # Fallback: simple X.Y.Z
        parts = list(map(int, version.split(".")))
        while len(parts) < KERNEL_VERSION_TUPLE_SIZE:
            parts.append(0)
        return tuple(parts[:KERNEL_VERSION_TUPLE_SIZE])

    def _clean_kernel_version(self, kernel: str) -> str:
        """
        Normalize kernel release string (from `uname -r`) to match pacman package version format.

        Kernel release format (uname -r)          -> Package version format (pacman -Q)
        --------------------------------------------------------------------------------
        linux:       7.2.8-arch1-2                -> 7.2.8.arch1-2
        linux-zen:   7.2.9-zen1-1-zen             -> 7.2.9.zen1-1
        linux-lts:   6.18.55-1-lts                -> 6.18.55-1

        The transformation:
        1. Replace hyphens with dots (except the last component which is pkgrel)
        2. Remove the trailing flavor suffix (-arch, -zen, -lts) that appears in
           kernel release but not in package version
        """
        # linux-lts: 6.18.55-1-lts -> 6.18.55-1
        if kernel.endswith("-lts"):
            return kernel[:-4]  # Remove "-lts"

        # linux-zen: 7.2.9-zen1-1-zen -> 7.2.9.zen1-1
        # The pattern is: <upstream>-zen<ver>-<pkgrel>-zen
        # Split on "-zen" and rejoin with dots, but preserve the last "-<pkgrel>"
        if "-zen" in kernel:
            # Find the last "-zen" (the flavor suffix) and remove it
            # Everything before that is: <upstream>-zen<ver>-<pkgrel>
            last_zen_idx = kernel.rfind("-zen")
            if last_zen_idx != -1:
                without_suffix = kernel[:last_zen_idx]
                # Convert hyphens to dots except the last one (pkgrel separator)
                parts = without_suffix.split("-", maxsplit=1)
                return ".".join(parts)

        # linux: 7.2.8-arch1-2 -> 7.2.8.arch1-2
        # The pattern is: <upstream>-arch<ver>-<pkgrel> (no trailing -arch)
        if "-arch" in kernel:
            parts = kernel.split("-", maxsplit=1)
            return ".".join(parts)

        # Fallback: just replace all hyphens with dots (shouldn't happen for Arch kernels)
        return kernel.replace("-", ".")

    def should_run(self) -> tuple[bool, str, SkipReason | None]:
        """
        Decide whether enough packages are pending to justify an upgrade.

        Applies the whole-task gate described in
        [`SystemUpdateSettings.min_repo_updates_threshold`][archcare.config.models.SystemUpdateSettings]:
        the system is only upgraded once at least that many *official repository* updates are
        pending.

        The gate covers the whole task, not just the repository half — a repo count below the
        threshold skips the AUR upgrade too. Repository updates are a good proxy for how far
        behind the system is, and most "AUR" packages are in practice covered by the official
        repos or the semi-official [Chaotic AUR](https://chaotic.aur.cx/) repository.

        A news acknowledgement gate then runs: if there are unread Arch news items and the user
        has not been prompted recently, the user is asked whether to proceed (declining is the
        normal path — `system-update` is a `MANUAL` task never wired to a systemd timer). The
        user is not asked again for ``news_acknowledge_cooldown_minutes`` (default 30) after the
        last prompt.

        Returns:
            (tuple[bool, str, SkipReason | None]): A tuple of:

                - `should_run` (`bool`): `True` when the threshold is met and (if applicable)
                    the user declined to proceed.
                - `reason` (`str`): Explanation when skipping; empty when running.
                - `skip_reason` (`SkipReason | None`): `NO_WORK_NEEDED` when skipping below
                    threshold; `USER_CANCELLED` when declining the news prompt; `None` otherwise.

        Raises:
            OSError: If the `checkupdates` query fails. Propagating is deliberate: without a
                working update query the task cannot know whether there is work, and a
                silent skip would hide a broken package manager behind a clean exit code.
                `BaseTask.run()` converts it into a task failure.
        """
        threshold = self.settings.system_update.min_repo_updates_threshold
        pending = self._pending_repo_updates()

        if len(pending) < threshold:
            return (
                False,
                f"Only {len(pending)} repository update(s) pending, below the configured "
                f"threshold of {threshold}.",
                SkipReason.NO_WORK_NEEDED,
            )

        # News acknowledgement gate
        proceed, reason, skip_reason = self._handle_unread_news_prompt()
        if not proceed:
            return False, reason, skip_reason
        return True, "", None

    def execute(self) -> TaskResult[SystemUpdateDetails]:
        """
        Run the system upgrade transaction.

        Nine phases, reported as a determinate progress bar:

        1. Open the progress bar.
        2. Query pending repository and AUR updates. Both queries capture output, so they are
           the only source of per-package names available to this method.
        3. Snapshot the pre-upgrade `pacman -Q` manifest.
        4. Back up the pacman sync database. A failure returns `FAILURE` immediately: a
           transaction without a safety net is never started.
        5. Run `pacman -Syu` with the progress bar paused, so pacman's own confirmation and
           conflict prompts render against a clean terminal.
        6. Record the snapper `pre` snapshot id, *before* the AUR step, so the number
           unambiguously refers to the state this task found rather than one the AUR half
           could have moved the system to.
        7. Run `paru -Sua`, also paused. A failure here is *not* fatal — it produces `PARTIAL`,
           because a failed AUR build says nothing about the state of the pacman sync
           database, and rolling that back would be wrong.
        8. Snapshot the post-upgrade manifest and diff it against the pre-upgrade one to
           report what the transaction removed.
        9. Collect pending `.pacnew` files, build the details, and write the recovery record.

        Returns:
            (TaskResult[SystemUpdateDetails]): `success` when both halves completed,
                `partial` when only the AUR half failed, or `failed` when the sync database
                could not be backed up (in which case nothing was changed).

        Raises:
            RuntimeError: If `pacman -Syu` exits non-zero. Raising rather than returning a
                failure is deliberate: `BaseTask.run()` turns a raised exception into a
                `rollback()` call, and restoring the sync database pacman already refreshed
                is the entire recovery story for an aborted transaction. The exit code is the
                only signal available, because stdio was inherited and both streams are empty.

        Side Effects:
            - Writes two manifests and a recovery record under
              [`recovery_dir`][archcare.config.models.AppSettings.recovery_dir].
            - Upgrades the system's packages.
            - Drives the injected progress reporter.
        """
        self.progress.start(total=self._STEP_COUNT)

        pending_repo = self._pending_repo_updates()

        with self.progress.spinner("Checking for AUR updates"):
            pending_aur = get_pending_aur_updates()
        logger.info(
            f"Upgrading {len(pending_repo)} repository and {len(pending_aur)} AUR package(s)"
        )

        manifests_dir = self.settings.recovery_dir / "manifests"
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.manifest_before = snapshot_package_manifest(manifests_dir / f"before_{timestamp}.txt")
        self.report_progress(TaskStep(name="Package manifest captured", status=TaskStatus.SUCCESS))

        with self.progress.pause():
            try:
                self.sync_db_backup = backup_sync_db(self.settings.recovery_dir / "sync-db")
            except OSError as e:
                logger.error(f"Failed to back up the pacman sync database: {e}")
                return failed(f"Failed to back up the pacman sync database: {e}", error=str(e))
        self.report_progress(TaskStep(name="Sync database backed up", status=TaskStatus.SUCCESS))

        with self.progress.pause():
            result = run_system_upgrade()
        if not result.success:
            # stdout/stderr are empty by design (inherited stdio) — the exit code is all we have.
            logger.error(f"pacman -Syu failed: {result}")
            raise RuntimeError(f"`pacman -Syu` failed with exit code {result.returncode}")
        self.report_progress(
            TaskStep(name="Repository packages upgraded", status=TaskStatus.SUCCESS)
        )

        # Taken right after pacman: snap-pac's `pre` snapshot is the rollback point for *this*
        # transaction, and the AUR half below would otherwise blur which run created it.
        if detect_btrfs_snapshot_tooling():
            self.pre_update_snapshot_id = get_latest_snapshot_id()
        self.report_progress(TaskStep(name="Snapshot id recorded", status=TaskStatus.SUCCESS))

        with self.progress.pause():
            aur_result = run_aur_upgrade()
        aur_succeeded = aur_result.success
        if not aur_succeeded:
            logger.error(f"paru -Sua failed: {aur_result}")
        self.report_progress(TaskStep(name="AUR packages upgraded", status=TaskStatus.SUCCESS))

        manifest_after = snapshot_package_manifest(manifests_dir / f"after_{timestamp}.txt")
        packages_removed = diff_manifests(self.manifest_before, manifest_after)
        self.report_progress(TaskStep(name="Package manifest diffed", status=TaskStatus.SUCCESS))

        pacnew_files = list_pacnew_files()
        details = SystemUpdateDetails(
            pre_update_snapshot_id=self.pre_update_snapshot_id,
            pacnew_files=pacnew_files,
            **self._build_details(
                pending_repo=pending_repo,
                pending_aur=pending_aur,
                aur_succeeded=aur_succeeded,
                packages_removed=packages_removed,
            ),
        )
        self._write_recovery_record(details, manifest_after)
        self.report_progress(TaskStep(name="Recovery record written", status=TaskStatus.SUCCESS))

        if not aur_succeeded:
            return partial(
                f"Upgraded {len(pending_repo)} repository package(s), but "
                f"{len(pending_aur)} AUR package(s) failed to build or install",
                details=details,
            )

        return success(
            f"Upgraded {len(pending_repo)} repository and {len(pending_aur)} AUR package(s)",
            details=details,
        )

    def post_execute(self, result: TaskResult[SystemUpdateDetails]) -> None:
        """
        Prune the pacman cache after a completed run and announce the outcome.

        Two independent jobs, both best effort:

        1. **Cache cleanup**, gated on `result.is_success()` only. A `PARTIAL` result means
           `paru -Sua` failed partway — some AUR packages are mid-build, some installed — and
           the repository half already replaced the installed versions of those packages. The
           cache holds the only artifacts that make a `pacman -U` downgrade possible; pruning
           it in that state removes the downgrade path for exactly the packages the user is
           about to debug, and the sync-DB rollback does not cover them (a failed AUR build
           deliberately does not trigger one). A user who wants the space back can run
           `paccache -rk<n>` themselves once the system is healthy again, which is a far
           cheaper mistake to make than a missing package.
        2. **Notification**, through the injected
           [`NotificationManager`][archcare.core.notifications.NotificationManager]. This task
           is `MANUAL` and can take many minutes, so the user may well have walked away by the
           time it ends; the notification is how they learn whether it worked. Sent on every
           terminal outcome — success, partial, and failure alike. A no-op when no manager was
           injected (unit tests, programmatic callers).

        Args:
            result (TaskResult[SystemUpdateDetails]): The result produced by `execute()`.

        Side Effects:
            - Deletes cached package files under `/var/cache/pacman/pkg` on a successful run.
            - Mutates `result.details` by replacing it with a copy carrying
              `cache_freed_bytes`; `SystemUpdateDetails` is a frozen dataclass, so it cannot
              be stamped in place.
            - Sends a desktop notification via `notify-send` when a manager is available.
            - Emits Loguru log messages at `debug`/`info`/`error` levels; every failure is
              logged and swallowed, never propagated.

        Note:
            Neither job may raise. [`BaseTask.run`][] calls this hook inside its `try` block,
            so an escaping exception would be caught, routed to `rollback()`, and report a
            successful upgrade as a failure *while rewinding the pacman sync database* — the
            exact damage this task exists to prevent.
        """
        if result.is_success():
            self._prune_package_cache(result)
        self._announce_outcome(result)

    def rollback(self) -> None:
        """
        Restore the pacman sync database after a failed transaction.

        Invoked automatically by [`BaseTask.run`][] when `execute()` raises — which happens
        exactly when `pacman -Syu` exits non-zero, *after* it has already refreshed the
        repository databases but before the install phase completed. Left as they are, those
        databases describe a newer repository state than the packages actually installed, so
        the next `pacman -Syu` would plan an upgrade against a state the system never reached.

        Nothing is done when no backup exists: either the run failed before the backup step
        (so nothing was refreshed either) or the backup itself failed, in which case
        `execute()` returns a failure and no transaction was ever started.

        Side Effects:
            - Copies the backup over `/var/lib/pacman/sync` (through `sudo`).
            - Emits Loguru log messages at `warning`/`info`/`error`/`critical` levels.

        Note:
            This method never propagates, deliberately. If the restore itself failed, the
            user has a genuinely broken repository database and a real problem to solve — but
            raising here would replace the `pacman -Syu` failure that caused the rollback in
            the first place with a secondary one, and the original error is the one that
            explains what happened. The path is logged at `critical` so the user can restore
            by hand.
        """
        if self.sync_db_backup is None:
            logger.warning("No pacman sync database backup available for rollback")
            return

        with self.progress.pause():
            try:
                logger.warning(f"Rolling back the pacman sync database from {self.sync_db_backup}")
                restore_sync_db(self.sync_db_backup)
                logger.info("Pacman sync database rollback completed")
            except Exception as e:
                logger.error(f"Failed to restore the pacman sync database: {e}")
                logger.critical(
                    "Repository databases may not match the installed packages! "
                    "Manually restore with: "
                    f"sudo cp -a {self.sync_db_backup}/. /var/lib/pacman/sync/"
                )

    def _prune_package_cache(self, result: TaskResult[SystemUpdateDetails]) -> None:
        """
        Run `paccache` and stamp the reclaimed byte count onto the result.

        Split out of `post_execute()` so the success gate and its reasoning stay readable, and so
        the swallowing `try` block covers the cache call without swallowing the notification as
        well.

        Args:
            result (TaskResult[SystemUpdateDetails]): A successful result. Its `details` are
                replaced with a copy carrying `cache_freed_bytes`; a `None` details payload
                leaves the result untouched.

        Side Effects:
            - Deletes cached package files.
            - Replaces `result.details`.
            - Emits Loguru log messages at `debug`/`error` levels; failures are swallowed.

        Note:
            `cache_keep_versions` and `cache_keep_uninstalled_versions` come from
            `SystemUpdateSettings` and are the user's declared downgrade depth, so
            they are read rather than defaulted.
        """
        settings = self.settings.system_update
        try:
            freed = clean_cache(
                keep=settings.cache_keep_versions,
                keep_uninstalled=settings.cache_keep_uninstalled_versions,
            )
        except Exception as e:
            logger.error(f"Package cache cleanup failed: {e}")
            return

        if result.details is not None:
            result.details = dataclasses.replace(result.details, cache_freed_bytes=freed)
        logger.debug(f"Package cache cleanup reclaimed {format_bytes(freed)}")

    def _announce_outcome(self, result: TaskResult[SystemUpdateDetails]) -> None:
        """
        Send a desktop notification describing how the run ended.

        `success=` is deliberately `result.is_success()`, so a `PARTIAL` run — the AUR half
        failed — is announced as a failure. The user needs to act on that, and a green tick
        would be the wrong summary of an upgrade that did not fully land.

        Args:
            result (TaskResult[SystemUpdateDetails]): The completed result.

        Side Effects:
            - Sends a desktop notification via `notify-send` when a manager is available.
            - Emits Loguru log messages at `error` level; a failing notifier is swallowed.

        Note:
            Never propagates, for the same reason as `post_execute()`: it is called from inside
            `run()`'s `try` block.
        """
        if self.notification_manager is None:
            return

        try:
            self.notification_manager.send_task_result_notification(
                task_name=self.name,
                success=result.is_success(),
                message=result.message,
            )
        except Exception as e:
            logger.error(f"Failed to send the system update notification: {e}")

    @staticmethod
    def _build_details(
        *,
        pending_repo: list[PackageUpdateInfo],
        pending_aur: list[PackageUpdateInfo],
        aur_succeeded: bool,
        packages_removed: list[str],
    ) -> dict[str, Any]:
        """
        Derive the per-package half of the details payload from pre-flight and diff sources.

        Both halves of the transaction run with stdio inherited, so **their own output cannot be
        parsed** — there is no captured stream to read the package list out of. Every list here
        therefore comes from a source that did capture output, or from the manifest diff:

        - `packages_upgraded` is the pre-flight repository query. `pacman -Syu` either applies
          every pending repository update or aborts, and an abort raises rather than reaching
          this method, so on the success path this list is exactly what was upgraded.
        - `aur_packages_upgraded` / `aur_packages_failed` are the pre-flight AUR query, split by
          whether `paru -Sua` succeeded. The real split is per-package and unknowable from here;
          when paru fails, every pending AUR package is reported as failed, because none can be
          assumed to have installed.
        - `packages_removed` is the actual diff of the two `pacman -Q` manifests.

        `pre_update_snapshot_id` and `cache_freed_bytes` are deliberately not set here: the
        first is known only once the snapshot is queried, and the second belongs to the cache
        cleanup that `post_execute()` runs in a later step.

        Args:
            pending_repo (list[PackageUpdateInfo]): Pending repository updates from the
                pre-flight query.
            pending_aur (list[PackageUpdateInfo]): Pending AUR updates from the pre-flight
                query.
            aur_succeeded (bool): Whether `paru -Sua` exited successfully.
            packages_removed (Sequence[str]): Names present in the pre-upgrade manifest but
                absent from the post-upgrade one.

        Returns:
            dict[str, Any]: Keyword arguments for `SystemUpdateDetails`, covering the counts and
                the four per-package lists.
        """
        aur_names = [update.name for update in pending_aur]
        return {
            "repo_updates_count": len(pending_repo),
            "aur_updates_count": len(pending_aur),
            "packages_upgraded": [update.name for update in pending_repo],
            "aur_packages_upgraded": aur_names if aur_succeeded else [],
            "aur_packages_failed": [] if aur_succeeded else aur_names,
            "packages_removed": list(packages_removed),
        }

    def _write_recovery_record(self, details: SystemUpdateDetails, manifest_after: Path) -> None:
        """
        Write the recovery record consumed by `archcare task recover system-update`.

        Records the artifacts a *successful* upgrade leaves behind — both manifests, the sync
        database backup, and the `pre` snapshot number — because none of them can be recreated
        after the fact: the pacman transaction is over and its output was never captured.

        Paths are stored as strings and `None` values serialise as JSON `null`, so the file is
        safe to read back with a plain `json.load` and hand to a human-facing command that
        prints `snapper rollback <id>`.

        Args:
            details (SystemUpdateDetails): The payload being written to the record.
            manifest_after (Path): The post-upgrade manifest to record.

        Side Effects:
            - Creates the recovery directory if missing and writes the record over any
              previous one, so the file always describes the most recent run.
            - Emits Loguru log messages at `debug`/`info` levels.
        """
        self.recovery_file.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "task": self.name,
            "updated_at": datetime.now().isoformat(),
            "sync_db_backup": str(self.sync_db_backup) if self.sync_db_backup else None,
            "manifest_before": str(self.manifest_before) if self.manifest_before else None,
            "manifest_after": str(manifest_after),
            "pre_update_snapshot_id": details.pre_update_snapshot_id,
            "packages_upgraded": details.packages_upgraded,
            "aur_packages_upgraded": details.aur_packages_upgraded,
            "aur_packages_failed": details.aur_packages_failed,
            "packages_removed": details.packages_removed,
        }
        self.recovery_file.write_text(json.dumps(record, indent=2), encoding="utf-8")
        logger.info(f"System update recovery record written to {self.recovery_file}")
