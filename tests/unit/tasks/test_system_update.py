"""
Unit tests for SystemUpdateTask (tasks/system_update.py).

Scope: All of the task-specific logic that genuinely deserve its own
unit tests, not a re-verification of the base task's behavior.
"""

import json
from collections.abc import Callable, Iterator
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial as functools_partial
from os.path import expanduser
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from _pytest.monkeypatch import MonkeyPatch

from archcare.config import AppSettings, SkipReason, TaskConfig
from archcare.core import (
    SystemUpdateDetails,
    TaskDependencies,
    failed,
    partial,
    success,
)
from archcare.core.interaction import TaskInteraction
from archcare.core.progress import TaskProgress
from archcare.tasks.system_update import SystemUpdateTask
from archcare.utils import PackageUpdateInfo
from archcare.utils.info_models import MirrorlistInfo
from archcare.utils.system import CommandResult

from .conftest import PromptGuardLedger, bind_guard_progress

_MODULE = "archcare.tasks.system_update"

# Fixed shape of the transaction the `transaction` fixture fakes, asserted by name so the
# expected values are stated once instead of repeated as bare literals in every test.
REPO_UPDATE_COUNT = 3
AUR_UPDATE_COUNT = 2
TRANSACTION_COUNT = 2
# `execute()` pauses for all four sudo-backed helpers (see the guard class at the bottom
# of this module). `post_execute()` adds one more pause around `clean_cache`, but this
# constant counts execute()'s phases only; runs taken end-to-end live elsewhere.
PAUSE_COUNT = 4
ANNOUNCED_STEPS = 7
SNAPSHOT_ID = 42
REMOVED_PACKAGES = ["linux-lts"]
PACNEW_FILES = ["/etc/pacman.conf.pacnew"]
CACHE_FREED_BYTES = 734003200

# Every test in this module constructs settings whose log_dir is redirected into tmp_path.
# Applying the fixture module-wide matches the convention in tests/unit/core/test_base_task.py
# and means no test here can reach the real home, including future ones.
pytestmark = pytest.mark.usefixtures("no_task_logging")


@pytest.fixture
def system_update_config() -> TaskConfig:
    return TaskConfig.model_validate(
        {
            "name": "system-update",
            "type": "manual",
            "frequency": 7,
            "description": "Update system packages and clean pacman cache",
            "enabled": True,
        }
    )


@pytest.fixture
def system_update_settings(tmp_path: Path, monkeypatch: MonkeyPatch) -> AppSettings:
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    return AppSettings(user=None)


@pytest.fixture
def task(
    task_deps: TaskDependencies,
    system_update_config: TaskConfig,
    system_update_settings: AppSettings,
) -> SystemUpdateTask:
    return SystemUpdateTask(
        config=system_update_config, settings=system_update_settings, deps=task_deps
    )


def _clear_static_gates(mocker, *, stale_mirrorlist=False) -> None:
    """
    Stub the two host-dependent `should_run()` gates that have nothing to do with the test.

    Gate 1 reads the real `/etc/pacman.d/mirrorlist` and gate 3 inspects `/usr/lib/modules`.
    Left unpatched, both make the outcome depend on the machine running the suite — which might
    not even be an Arch linux system. Patching the utils boundary (not the filesystem) keeps these
    tests hermetic while still exercising the gate code itself.
    """
    fresh = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stale = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
    mocker.patch(
        f"{_MODULE}.get_mirrorlist_info",
        return_value=MirrorlistInfo(last_modified=stale if stale_mirrorlist else fresh),
    )
    mocker.patch(f"{_MODULE}.get_pending_kernel_reboot", return_value=None)


def _updates(count: int) -> list[PackageUpdateInfo]:
    """Build `count` distinct pending-update entries."""
    return [
        PackageUpdateInfo(name=f"pkg{i}", old_version="1.0-1", new_version="2.0-1")
        for i in range(count)
    ]


def _unread_news(mocker, headlines: list[str] | None = None) -> None:
    """
    Stub the two calls the news gate makes once `has_unread_arch_news()` reports `True`.

    `headlines` defaults to empty, which is what a real `informant`/`paru` run that cannot be
    parsed into titles yields — the prompt then falls back to generic wording.
    """
    mocker.patch(f"{_MODULE}.has_unread_arch_news", return_value=True)
    mocker.patch(
        f"{_MODULE}.fetch_arch_news_headlines",
        return_value=headlines if headlines else [],
    )


def _interaction(task: SystemUpdateTask, *, confirm: bool = True) -> MagicMock:
    """
    Inject a specced interaction port into `task` whose `confirm()` answers with `confirm`.

    Returned so a test can assert on `confirm.assert_called_once()` /
    `confirm.assert_not_called()`. A specced mock keeps the port's contract honest: a call to a
    method `TaskInteraction` does not define fails loudly instead of silently passing.
    """
    interaction = MagicMock(spec=TaskInteraction)
    interaction.confirm.return_value = confirm
    task.interaction = interaction
    return interaction


def _prompted_at(task: SystemUpdateTask, when: datetime | None) -> MagicMock:
    """
    Give `task` a persisted state whose `system-update` entry was last prompted at `when`.

    `when=None` models a user who has never been prompted, which is what makes the cooldown
    inapplicable. Only `last_news_prompt` is set, because that is the single field the news gate
    reads — setting the rest of `TaskState` would imply they matter when they do not.

    Returns:
        MagicMock: The state, so a test can assert the gate recorded a new prompt timestamp
            via `state.set_task_news_prompt`.
    """
    task.state = MagicMock()
    task.state.tasks = {"system-update": MagicMock(last_news_prompt=when)}
    return task.state


def _ok(command: str = "mock") -> CommandResult:
    """
    A successful `CommandResult`.

    `stdout`/`stderr` are empty exactly as they are in production: both transaction helpers run
    with stdio inherited, so the exit code is the only signal a test may rely on.
    """
    return CommandResult(command=command, returncode=0, stdout="", stderr="", success=True)


def _fail(command: str = "mock", returncode: int = 1) -> CommandResult:
    """A failed `CommandResult` with empty streams, mirroring inherited stdio."""
    return CommandResult(
        command=command, returncode=returncode, stdout="", stderr="", success=False
    )


@pytest.fixture
def mock_progress() -> MagicMock:
    """
    A progress port that records `advance`/`pause` calls and stays a working context manager.

    `MagicMock(spec=TaskProgress)` would make `pause()` return a MagicMock, and `with
    mock.pause():` would be a no-op that still counts as a call — enough for the call-count
    assertions, but a real `nullcontext` keeps the "did anything happen inside the paused
    block" assertions honest too.
    """
    progress = MagicMock(spec=TaskProgress)
    progress.pause.return_value = nullcontext()
    return progress


@dataclass
class _Wiring:
    """
    Handles for the OS-boundary stubs installed by the `transaction` fixture.

    Returning the mocks (instead of the bare `mocker` object) keeps every test free of
    pytest-mock internals: `transaction.mocks["run_system_upgrade"]` reads as what it is, and
    `transaction.override(name, ...)` re-stubs one helper for a single test.
    """

    patch: Callable[..., MagicMock]
    mocks: dict[str, MagicMock]
    progress: MagicMock

    def override(self, name: str, **kwargs) -> MagicMock:
        """Re-stub one helper for the current test, leaving the rest of the wiring intact."""
        return self.patch(f"{_MODULE}.{name}", **kwargs)


@pytest.fixture
def transaction(task: SystemUpdateTask, mocker, mock_progress: MagicMock) -> _Wiring:
    """
    Wire every OS boundary `execute()` touches, so the transaction runs fully in memory.

    `execute()` reaches the real system through exactly these helpers, and two of them
    (`run_system_upgrade`, `run_aur_upgrade`) would actually attempt to modify this machine.
    Tests that call `execute()` must use this fixture rather than patching ad hoc, so no future
    edit to the orchestration can silently reintroduce a real subprocess call.

    `snapshot_package_manifest` is stubbed with a writer rather than a bare return value: the
    task chains `diff_manifests` around real files, and
    `test_writes_both_manifests_under_recovery_dir` needs them to actually exist.
    """

    def _manifest(destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("linux 6.10\nvim 9.0\n", encoding="utf-8")
        return destination

    backup = task.settings.recovery_dir / "sync-db" / "sync-db_2026-01-01_000000"
    stubs: dict[str, dict[str, Any]] = {
        "check_command_exists": {"return_value": True},
        "has_interactive_terminal": {"return_value": True},
        "has_unread_arch_news": {"return_value": False},
        "get_pending_repo_updates": {"return_value": _updates(REPO_UPDATE_COUNT)},
        "get_pending_aur_updates": {"return_value": _updates(AUR_UPDATE_COUNT)},
        "get_latest_snapshot_id": {"return_value": None},
        "snapshot_package_manifest": {"side_effect": _manifest},
        "backup_sync_db": {"return_value": backup},
        "restore_sync_db": {"return_value": None},
        "clean_cache": {"return_value": 0},
        "get_pending_kernel_reboot": {"return_value": None},
        "run_system_upgrade": {"return_value": _ok()},
        "run_aur_upgrade": {"return_value": _ok()},
        "detect_btrfs_snapshot_tooling": {"return_value": False},
        "diff_manifests": {"return_value": REMOVED_PACKAGES},
        "list_pacnew_files": {"return_value": PACNEW_FILES},
    }
    mocks: dict[str, MagicMock] = {
        name: mocker.patch(f"{_MODULE}.{name}", **kwargs) for name, kwargs in stubs.items()
    }

    task.progress = mock_progress
    return _Wiring(patch=mocker.patch, mocks=mocks, progress=mock_progress)


@pytest.fixture
def prompt_guard(
    prompt_guard_ledger: PromptGuardLedger, mocker, tmp_path: Path
) -> PromptGuardLedger:
    """
    Wire `execute()`, `post_execute()`, and `rollback()` with only the OS boundary faked.

    The real utils helpers run (manifest snapshot/diff, backup, cache cleanup, snapper
    lookup); the shared ledger's recorders answer every wrapper call. Only this task's
    specifics live here: canned stdout for the read-only queries real helpers issue, a
    hermetic `SYNC_DB_PATH`, a rebuilt-to-the-real-`clean_cache` with a tmp `cache_dir`, and
    the snapper branch forced on — that lookup stays REAL because its sudo call is precisely
    what the guard must see.
    """
    ledger = prompt_guard_ledger
    ledger.canned_stdout.update(
        {
            ("checkupdates", "--nocolor"): "linux 6.10.1-1 -> 6.10.2-1\n",
            ("pacman", "-Q"): "linux 6.10\nvim 9.0\n",
        }
    )

    sync_db = tmp_path / "sync"
    sync_db.mkdir()
    mocker.patch("archcare.utils.pacman.SYNC_DB_PATH", new=sync_db)

    mocker.patch(f"{_MODULE}.detect_btrfs_snapshot_tooling", return_value=True)

    from archcare.utils.pacman import clean_cache as _real_clean_cache

    mocker.patch(
        f"{_MODULE}.clean_cache",
        new=functools_partial(_real_clean_cache, cache_dir=tmp_path / "pac-cache"),
    )

    return ledger


class TestPreCheckCommands:
    def test_missing_pacman_blocks_with_arch_wiki_guide(self, mocker, task: SystemUpdateTask):
        mocker.patch(f"{_MODULE}.check_command_exists", return_value=False)

        can_run, reason = task.pre_check()

        assert can_run is False
        assert "Arch wiki" in reason
        assert "https://wiki.archlinux.org/" in reason

    def test_missing_checkupdates_blocks_with_install_hint(self, task: SystemUpdateTask, mocker):
        """
        `checkupdates` ships in `pacman-contrib` — the hint must name that package, not the command.
        """
        mocker.patch(
            f"{_MODULE}.check_command_exists",
            side_effect=lambda cmd: cmd != "checkupdates",
        )
        mocker.patch(f"{_MODULE}.has_interactive_terminal", return_value=True)

        can_run, reason = task.pre_check()

        assert can_run is False
        assert "checkupdates" in reason
        assert "sudo pacman -S pacman-contrib" in reason

    def test_missing_paru_blocks_with_aur_install_hint(self, task: SystemUpdateTask, mocker):
        """
        `paru` is an AUR package — the hint must NOT suggest `sudo pacman -S paru`.

        pacman cannot install AUR packages, so the hint points at building paru from
        the AUR with `makepkg` (or installing it via another AUR helper) instead.
        """
        mocker.patch(
            f"{_MODULE}.check_command_exists",
            side_effect=lambda cmd: cmd != "paru",
        )
        mocker.patch(f"{_MODULE}.has_interactive_terminal", return_value=True)

        can_run, reason = task.pre_check()

        assert can_run is False
        assert "paru" in reason
        assert "sudo pacman -S paru" not in reason
        assert "makepkg" in reason
        assert "aur.archlinux.org/paru" in reason


class TestPreCheckTerminal:
    def test_missing_terminal_blocks(self, task: SystemUpdateTask, mocker):
        mocker.patch(f"{_MODULE}.check_command_exists", return_value=True)
        mocker.patch(f"{_MODULE}.has_interactive_terminal", return_value=False)

        can_run, reason = task.pre_check()

        assert can_run is False
        assert "interactive terminal" in reason

    def test_terminal_is_the_last_pre_check(self, task: SystemUpdateTask, mocker):
        """Every command present but no TTY: the terminal verdict is what gets reported."""
        mocker.patch(f"{_MODULE}.check_command_exists", return_value=True)
        mocker.patch(f"{_MODULE}.has_interactive_terminal", return_value=False)

        can_run, reason = task.pre_check()

        assert can_run is False
        assert "interactive terminal" in reason
        assert "`pacman` not found" not in reason

    def test_all_prerequisites_present_passes(self, task: SystemUpdateTask, mocker):
        """
        `pre_check()` is purely static: a clean host returns `(True, "")` with no stubs.

        Deliberately patches *nothing* else — `should_run()` owns the host-dependent gates, so a
        passing `pre_check()` must not require any of them to be stubbed first.
        """
        mocker.patch(f"{_MODULE}.check_command_exists", return_value=True)
        mocker.patch(f"{_MODULE}.has_interactive_terminal", return_value=True)

        assert task.pre_check() == (True, "")


class TestShouldRunMirrorlist:
    """Gate 1 of `should_run()`: a stale mirrorlist blocks before any update query runs."""

    def test_stale_mirrorlist_blocks(self, task: SystemUpdateTask, mocker):
        _clear_static_gates(mocker, stale_mirrorlist=True)

        should_run, reason, skip_reason = task.should_run()

        assert should_run is False
        assert skip_reason == SkipReason.MIRRORLIST_STALE
        assert "older than 7 days" in reason
        assert "mirrorlist-update" in reason

    def test_stale_mirrorlist_names_the_configured_path(self, task: SystemUpdateTask, mocker):
        """The message must name the path that is actually stale, not a hardcoded default."""
        _clear_static_gates(mocker, stale_mirrorlist=True)
        task.settings.mirrorlist.path = Path("/etc/pacman.d/custom-mirrorlist")

        _, reason, _ = task.should_run()

        assert "/etc/pacman.d/custom-mirrorlist" in reason

    def test_unresolvable_mirrorlist_does_not_block(self, task: SystemUpdateTask, mocker):
        """
        A missing mirrorlist file yields `last_modified is None` — unknown, not stale.

        Failing open here is deliberate: the task must not invent a staleness verdict from an
        absent file, which is exactly the state `mirrorlist-update` is about to fix.
        """
        _clear_static_gates(mocker)
        mocker.patch(f"{_MODULE}.get_mirrorlist_info", return_value=MirrorlistInfo())
        mocker.patch(f"{_MODULE}.get_pending_repo_updates", return_value=_updates(30))
        mocker.patch(f"{_MODULE}.has_unread_arch_news", return_value=False)

        assert task.should_run() == (True, "", None)

    def test_mirrorlist_gate_runs_before_the_update_query(self, task: SystemUpdateTask, mocker):
        """A stale mirrorlist must short-circuit: no network query is spent on a known blocker."""
        _clear_static_gates(mocker, stale_mirrorlist=True)
        query: MagicMock = mocker.patch(f"{_MODULE}.get_pending_repo_updates")

        task.should_run()

        query.assert_not_called()

    def test_seven_day_old_mirrorlist_still_passes(self, task: SystemUpdateTask, mocker):
        """The threshold is strict (`> 7` days), so exactly seven days is not yet stale."""
        _clear_static_gates(mocker)
        edge = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        mocker.patch(
            f"{_MODULE}.get_mirrorlist_info",
            return_value=MirrorlistInfo(last_modified=edge),
        )
        mocker.patch(f"{_MODULE}.get_pending_repo_updates", return_value=_updates(30))
        mocker.patch(f"{_MODULE}.has_unread_arch_news", return_value=False)

        assert task.should_run() == (True, "", None)

    def test_just_over_the_threshold_blocks(self, task: SystemUpdateTask, mocker):
        """Eight days is one day past the strict threshold — the smallest blocking delta."""
        _clear_static_gates(mocker)
        edge = (datetime.now() - timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S")
        mocker.patch(
            f"{_MODULE}.get_mirrorlist_info",
            return_value=MirrorlistInfo(last_modified=edge),
        )
        mocker.patch(f"{_MODULE}.get_pending_repo_updates", return_value=_updates(30))
        mocker.patch(f"{_MODULE}.has_unread_arch_news", return_value=False)

        should_run, _, skip_reason = task.should_run()

        assert should_run is False
        assert skip_reason == SkipReason.MIRRORLIST_STALE

    def test_mirrorlist_gate_beats_the_reboot_gate(self, task: SystemUpdateTask, mocker):
        """
        A stale mirrorlist is reported ahead of a pending reboot: it is the cheaper fix.

        Telling someone to reboot when `archcare task run mirrorlist-update` is all that is
        needed would send them through a much heavier remedy for no reason.
        """
        _clear_static_gates(mocker, stale_mirrorlist=True)
        mocker.patch(
            f"{_MODULE}.get_pending_repo_updates",
            return_value=_updates(30),
        )
        mocker.patch(
            f"{_MODULE}.get_pending_kernel_reboot",
            return_value=("6.12.1-arch1-1", ["6.12.2.arch1-1"]),
        )

        _, reason, skip_reason = task.should_run()

        assert skip_reason == SkipReason.MIRRORLIST_STALE
        assert "Pending reboot" not in reason

    def test_stale_mirrorlist_uses_configurable_threshold(self, task: SystemUpdateTask, mocker):
        """The staleness gate reads threshold from SystemUpdateSettings."""
        _clear_static_gates(mocker, stale_mirrorlist=True)
        # Default threshold is 7; make it 3 so a 10-day stale mirrorlist clearly exceeds it
        task.settings.system_update.mirrorlist_stale_threshold_days = 3
        # Re-patch with 10-day stale to ensure it exceeds the configured 3-day threshold
        stale_10 = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
        mocker.patch(
            f"{_MODULE}.get_mirrorlist_info", return_value=MirrorlistInfo(last_modified=stale_10)
        )
        mocker.patch(f"{_MODULE}.get_pending_repo_updates", return_value=_updates(30))
        mocker.patch(f"{_MODULE}.has_unread_arch_news", return_value=False)

        should_run, reason, skip_reason = task.should_run()
        assert should_run is False
        assert skip_reason == SkipReason.MIRRORLIST_STALE
        assert "older than 3 days" in reason


class TestShouldRunReboot:
    """
    Gate 3 of `should_run()`: a replaced running kernel blocks until the user reboots.

    The gate sits *after* the threshold gate on purpose — there is no point telling someone to
    reboot when there is nothing to install — and *before* the news prompt, so the news
    acknowledgement doesn't come before a pending reboot which would block the task
    execution anyway.
    """

    def test_pending_reboot_blocks(self, task: SystemUpdateTask, mocker):
        _clear_static_gates(mocker)
        mocker.patch(f"{_MODULE}.get_pending_repo_updates", return_value=_updates(30))
        mocker.patch(
            f"{_MODULE}.get_pending_kernel_reboot",
            return_value=("6.12.1-arch1-1", ["6.12.2.arch1-1"]),
        )

        should_run, reason, skip_reason = task.should_run()

        assert should_run is False
        assert skip_reason == SkipReason.REBOOT_REQUIRED
        assert "Pending reboot" in reason
        assert "6.12.1-arch1-1" in reason
        assert "6.12.2.arch1-1" in reason
        assert "Reboot" in reason

    def test_reboot_message_lists_every_installed_kernel(self, task: SystemUpdateTask, mocker):
        """A multi-kernel system must show all of them, not just one misidentified target."""
        _clear_static_gates(mocker)
        mocker.patch(f"{_MODULE}.get_pending_repo_updates", return_value=_updates(30))
        mocker.patch(
            f"{_MODULE}.get_pending_kernel_reboot",
            return_value=("7.2.0.arch1-1", ["7.2.0.arch1-1", "6.18.35-1-lts"]),
        )

        _, reason, _ = task.should_run()

        assert "7.2.0.arch1-1, 6.18.35-1-lts" in reason

    def test_pending_reboot_skips_the_news_prompt(self, task: SystemUpdateTask, mocker):
        """The reboot verdict wins over the news prompt: don't ask about news, ask for a reboot."""
        _clear_static_gates(mocker)
        mocker.patch(f"{_MODULE}.get_pending_repo_updates", return_value=_updates(30))
        mocker.patch(f"{_MODULE}.has_unread_arch_news", return_value=True)
        mocker.patch(
            f"{_MODULE}.get_pending_kernel_reboot",
            return_value=("6.12.1-arch1-1", ["6.12.2.arch1-1"]),
        )
        interaction = _interaction(task)

        _, _, skip_reason = task.should_run()

        assert skip_reason == SkipReason.REBOOT_REQUIRED
        interaction.confirm.assert_not_called()

    def test_current_kernel_proceeds(self, task: SystemUpdateTask, mocker):
        """`None` from the utils probe means the running kernel is current — nothing to block on."""
        _clear_static_gates(mocker)
        mocker.patch(f"{_MODULE}.get_pending_repo_updates", return_value=_updates(30))
        mocker.patch(f"{_MODULE}.has_unread_arch_news", return_value=False)

        assert task.should_run() == (True, "", None)

    def test_reboot_gate_is_skipped_below_the_threshold(self, task: SystemUpdateTask, mocker):
        """Nothing to install means no reboot check — and no `/usr/lib/modules` scan."""
        _clear_static_gates(mocker)
        mock_reboot: MagicMock = mocker.patch(f"{_MODULE}.get_pending_kernel_reboot")
        mocker.patch(f"{_MODULE}.get_pending_repo_updates", return_value=_updates(2))

        should_run, _, skip_reason = task.should_run()

        assert should_run is False
        assert skip_reason == SkipReason.NO_WORK_NEEDED
        mock_reboot.assert_not_called()


class TestRequiresReboot:
    """
    `_requires_reboot()` translates the utils probe into a user-facing message.

    The pkgbase detection itself (directory scan, `OSError` handling, running-kernel matching)
    belongs to `get_pending_kernel_reboot` and is covered in its corresponding unit test; these
    tests cover only the message formatting.
    """

    def test_returns_empty_when_nothing_is_pending(self, task: SystemUpdateTask, mocker):
        mocker.patch(f"{_MODULE}.get_pending_kernel_reboot", return_value=None)

        assert task._requires_reboot() == ""

    def test_returns_a_message_when_the_running_kernel_was_replaced(
        self, task: SystemUpdateTask, mocker
    ):
        mocker.patch(
            f"{_MODULE}.get_pending_kernel_reboot",
            return_value=("7.2.8-arch1-1", ["7.2.9.arch1-1"]),
        )

        result = task._requires_reboot()

        assert result.startswith("Pending reboot")
        assert "the running kernel (7.2.8-arch1-1) was replaced by an upgrade" in result
        assert "installed: 7.2.9.arch1-1" in result
        assert "Reboot, then re-run." in result

    def test_delegates_the_probe_to_the_utils_helper(self, task: SystemUpdateTask, mocker):
        """The gate must not re-implement detection; it must call the shared helper."""
        mock_reboot: MagicMock = mocker.patch(
            f"{_MODULE}.get_pending_kernel_reboot", return_value=None
        )

        task._requires_reboot()

        mock_reboot.assert_called_once()


class TestRecoveryFilePath:
    def test_is_under_recovery_dir(self, task: SystemUpdateTask):
        assert task.recovery_file == task.settings.recovery_dir / "system-update.json"


class TestHomeIsolation:
    """
    Guards against this module ever writing into the developer's real home.

    `run()` creates a log file at `settings.log_dir/tasks/<name>.log`. If the
    `Path.home` redirect in `system_update_settings` is ever dropped, weakened, or defeated by the
    `SUDO_USER` indirection in the `AppSettings.home_dir` indirection, the file silently lands in
    `~/.local/state/archcare/logs/tasks/` — the test still passes, so nothing else would
    catch it. These assertions fail loudly instead.

    Every test here requests `transaction` so the whole transaction runs against the 13 stubs
    rather than patching the handful of names this class happened to need.
    """

    @staticmethod
    def _real_home_tasks_log() -> Path:
        """
        The real `~/.local/state/archcare/logs/tasks`, independent of the fixture.

        `system_update_settings` monkeypatches `Path.home()`, so calling it here would just
        hand back tmp_path and the assertion would be vacuous. `expanduser` reads $HOME
        directly and is unaffected by that patch.
        """
        return Path(expanduser("~")) / ".local/state/archcare/logs/tasks"

    def test_settings_resolve_under_tmp_path(self, task: SystemUpdateTask, tmp_path: Path):
        assert task.settings.log_dir.is_relative_to(tmp_path)

    @pytest.mark.usefixtures("transaction")
    def test_run_writes_no_log_file_into_the_real_home(self, task: SystemUpdateTask):
        real_log = self._real_home_tasks_log() / "system-update.log"
        # If a log file already exists in the real home, it means either:
        #
        # 1. Real task execution produced logs (which is regular behavior for the real task)
        # 2. The log file from a PREVIOUS test run escaped the tmp_path redirect.
        #
        # Skip with a clear message rather than fail, because the current run's redirect may be
        # working correctly.
        if real_log.exists():
            pytest.skip(
                f"Log file {real_log} exists; skipping to avoid false-positive. "
                "Delete it to re-enable this guard test."
            )

        task.run()

        assert not real_log.exists()


class TestPendingRepoUpdateCache:
    def test_queries_once_across_repeated_calls(self, task: SystemUpdateTask, mocker):
        query = mocker.patch(f"{_MODULE}.get_pending_repo_updates", return_value=[])

        task._pending_repo_updates()
        task._pending_repo_updates()

        assert query.call_count == 1

    def test_caches_an_empty_result(self, task: SystemUpdateTask, mocker):
        """An empty list is a legitimate result and must be cached, not re-queried."""
        query = mocker.patch(f"{_MODULE}.get_pending_repo_updates", return_value=[])

        first = task._pending_repo_updates()
        second = task._pending_repo_updates()

        assert first is second
        assert first == second == []
        assert query.call_count == 1


class TestShouldRunPendingRepo:
    """
    Gate 2 of `should_run()`: the `min_repo_updates_threshold` batching gate.

    `_clear_static_gates` is applied by every test here because the mirrorlist and reboot gates
    run *before* this one; without it the outcome would depend on the developer's machine.
    """

    def test_skips_below_threshold(self, task: SystemUpdateTask, mocker):
        _clear_static_gates(mocker)
        mocker.patch(f"{_MODULE}.get_pending_repo_updates", return_value=_updates(4))
        mocker.patch(f"{_MODULE}.has_unread_arch_news", return_value=False)

        should_run, reason, skip_reason = task.should_run()

        assert should_run is False
        assert skip_reason == SkipReason.NO_WORK_NEEDED
        assert "4" in reason
        assert "30" in reason

    def test_skips_when_one_below_threshold(self, task: SystemUpdateTask, mocker):
        _clear_static_gates(mocker)
        mocker.patch(f"{_MODULE}.get_pending_repo_updates", return_value=_updates(29))
        mocker.patch(f"{_MODULE}.has_unread_arch_news", return_value=False)

        should_run, _, _ = task.should_run()

        assert should_run is False

    def test_runs_at_exactly_the_threshold(self, task: SystemUpdateTask, mocker):
        """30 pending updates meets the default threshold of 30: the boundary is inclusive."""
        _clear_static_gates(mocker)
        mocker.patch(f"{_MODULE}.get_pending_repo_updates", return_value=_updates(30))
        mocker.patch(f"{_MODULE}.has_unread_arch_news", return_value=False)

        assert task.should_run() == (True, "", None)

    def test_runs_above_threshold(self, task: SystemUpdateTask, mocker):
        _clear_static_gates(mocker)
        mocker.patch(f"{_MODULE}.get_pending_repo_updates", return_value=_updates(45))
        mocker.patch(f"{_MODULE}.has_unread_arch_news", return_value=False)

        assert task.should_run() == (True, "", None)

    def test_runs_with_zero_pending_when_threshold_is_zero(self, task: SystemUpdateTask, mocker):
        """A user who sets the threshold to 0 opts into updating on every run."""
        _clear_static_gates(mocker)
        mocker.patch(f"{_MODULE}.get_pending_repo_updates", return_value=[])
        mocker.patch(f"{_MODULE}.has_unread_arch_news", return_value=False)
        task.settings.system_update.min_repo_updates_threshold = 0

        assert task.should_run() == (True, "", None)

    def test_honours_a_custom_threshold(self, task: SystemUpdateTask, mocker):
        _clear_static_gates(mocker)
        task.settings.system_update.min_repo_updates_threshold = 1
        mocker.patch(f"{_MODULE}.get_pending_repo_updates", return_value=_updates(1))
        mocker.patch(f"{_MODULE}.has_unread_arch_news", return_value=False)

        assert task.should_run() == (True, "", None)

    def test_skips_with_a_raised_threshold(self, task: SystemUpdateTask, mocker):
        """Raising the threshold above what is pending must skip, not run."""
        _clear_static_gates(mocker)
        task.settings.system_update.min_repo_updates_threshold = 200
        mocker.patch(f"{_MODULE}.get_pending_repo_updates", return_value=_updates(45))
        mocker.patch(f"{_MODULE}.has_unread_arch_news", return_value=False)

        should_run, reason, skip_reason = task.should_run()

        assert should_run is False
        assert skip_reason == SkipReason.NO_WORK_NEEDED
        assert "200" in reason

    def test_threshold_skip_does_not_prompt_about_news(self, task: SystemUpdateTask, mocker):
        """Batching means quiet: a skip below the threshold must not ask the user anything."""
        _clear_static_gates(mocker)
        mocker.patch(f"{_MODULE}.get_pending_repo_updates", return_value=_updates(2))
        mocker.patch(f"{_MODULE}.has_unread_arch_news", return_value=True)
        interaction = _interaction(task)

        _, _, skip_reason = task.should_run()

        assert skip_reason == SkipReason.NO_WORK_NEEDED
        interaction.confirm.assert_not_called()

    def test_propagates_a_failing_update_query(self, task: SystemUpdateTask, mocker):
        """A broken package manager must surface, not silently skip."""
        _clear_static_gates(mocker)
        mocker.patch(
            f"{_MODULE}.get_pending_repo_updates",
            side_effect=OSError("checkupdates failed (exit 2)"),
        )
        mocker.patch(f"{_MODULE}.has_unread_arch_news", return_value=False)

        with pytest.raises(OSError, match="checkupdates failed"):
            task.should_run()

    def test_skips_when_user_declines_unread_news(self, task: SystemUpdateTask, mocker):
        """User declining to read news must skip the update."""
        _clear_static_gates(mocker)
        mocker.patch.object(task, "_pending_repo_updates", return_value=_updates(30))
        mocker.patch.object(
            task,
            "_handle_unread_news_prompt",
            return_value=(False, "skipped", SkipReason.USER_CANCELLED),
        )

        should_run, reason, skip_reason = task.should_run()

        assert should_run is False
        assert skip_reason == SkipReason.USER_CANCELLED
        assert reason == "skipped"

    def test_runs_when_user_acknowledges_news(self, task: SystemUpdateTask, mocker):
        """User acknowledges news -> run."""
        _clear_static_gates(mocker)
        mocker.patch.object(task, "_pending_repo_updates", return_value=_updates(30))
        mocker.patch.object(task, "_handle_unread_news_prompt", return_value=(True, "", None))

        should_run, reason, skip_reason = task.should_run()

        assert should_run is True
        assert reason == ""
        assert skip_reason is None

    def test_news_gate_is_last(self, task: SystemUpdateTask, mocker):
        """
        Only the news gate may prompt: it is reached after all the cheap deterministic gates.

        Patching it here (rather than `_pending_repo_updates`) is what proves the ordering — the
        news helper returns a refusal, so if any earlier gate had already blocked, the refusal
        would never be observed and the skip reason would not be `USER_CANCELLED`.
        """
        _clear_static_gates(mocker)
        mocker.patch.object(
            task,
            "_handle_unread_news_prompt",
            return_value=(False, "declined", SkipReason.USER_CANCELLED),
        )
        mock_repo: MagicMock = mocker.patch(
            f"{_MODULE}.get_pending_repo_updates", return_value=_updates(30)
        )

        should_run, reason, skip_reason = task.should_run()

        assert should_run is False
        assert skip_reason == SkipReason.USER_CANCELLED
        assert reason == "declined"
        # The threshold gate must have passed for the news gate to be reached at all.
        mock_repo.assert_called_once()


class TestNewsAcknowledgement:
    def test_noop_when_no_news_tool_installed(self, task: SystemUpdateTask, mocker):
        """
        Missing news tools must not block a non-interactive-style run.

        `has_unread_arch_news()` fails open, so this is the contract the gate relies on: the
        gate never re-checks for the tool itself, it simply trusts `False` to mean "nothing
        unread or unknowable" and proceeds.
        """
        mocker.patch(f"{_MODULE}.has_unread_arch_news", return_value=False)

        assert task._handle_unread_news_prompt() == (True, "", None)

    def test_noop_does_not_touch_the_interaction_port(self, task: SystemUpdateTask, mocker):
        """No news means no question asked — the interaction port must stay unused."""
        mocker.patch(f"{_MODULE}.has_unread_arch_news", return_value=False)
        interaction = _interaction(task)

        assert task._handle_unread_news_prompt() == (True, "", None)
        interaction.confirm.assert_not_called()

    def test_headlines_are_included_in_the_prompt_when_available(
        self, task: SystemUpdateTask, mocker
    ):
        """Headlines must reach the user verbatim — they are the whole point of the prompt."""
        mocker.patch(f"{_MODULE}.has_unread_arch_news", return_value=True)
        mocker.patch(
            f"{_MODULE}.fetch_arch_news_headlines",
            return_value=["`python` 3.13.0-2 requires manual intervention", "News item two"],
        )
        interaction = _interaction(task, confirm=True)

        task._handle_unread_news_prompt()

        prompt = interaction.confirm.call_args.args[0]
        assert "python` 3.13.0-2 requires manual intervention" in prompt
        assert "News item two" in prompt

    def test_fallback_prompt_when_no_headlines_can_be_fetched(self, task: SystemUpdateTask, mocker):
        """An unread-news signal with no parseable headlines still prompts, generically."""
        _unread_news(mocker)
        interaction = _interaction(task, confirm=True)

        task._handle_unread_news_prompt()

        prompt = interaction.confirm.call_args.args[0]
        assert "unread Arch Linux news items" in prompt
        assert "archlinux.org/news" in prompt

    def test_no_state_means_no_cooldown(self, task: SystemUpdateTask, mocker):
        """With no persisted state there is no memory of a previous prompt, so it must ask again."""
        _unread_news(mocker)
        interaction = _interaction(task, confirm=True)
        task.state = None

        assert task._handle_unread_news_prompt() == (True, "", None)
        interaction.confirm.assert_called_once()

    def test_recording_is_skipped_without_state(self, task: SystemUpdateTask):
        """`_record_news_prompt()` must not explode when there is nothing to persist to."""
        task.state = None

        task._record_news_prompt()  # must not raise

    def test_cooldown_window_honours_the_configured_minutes(self, task: SystemUpdateTask, mocker):
        """A custom cooldown must be respected, not the hardcoded 30-minute default."""
        mocker.patch(f"{_MODULE}.has_unread_arch_news", return_value=True)
        task.settings.system_update.news_acknowledge_cooldown_minutes = 120
        interaction = _interaction(task)
        task.state = MagicMock()
        task.state.tasks = {
            "system-update": MagicMock(
                last_news_prompt=datetime.now() - timedelta(minutes=90), last_status=None
            )
        }

        assert task._handle_unread_news_prompt() == (True, "", None)
        interaction.confirm.assert_not_called()

    def test_zero_cooldown_always_prompts(self, task: SystemUpdateTask, mocker):
        """A cooldown of 0 disables the window entirely, so a prompt is due immediately."""
        _unread_news(mocker)
        task.settings.system_update.news_acknowledge_cooldown_minutes = 0
        interaction = _interaction(task, confirm=True)
        task.state = _prompted_at(task, datetime.now())

        assert task._handle_unread_news_prompt() == (True, "", None)
        interaction.confirm.assert_called_once()

    def test_missing_task_state_entry_means_no_cooldown(self, task: SystemUpdateTask, mocker):
        """A state file with no entry for this task behaves like never-prompted."""
        _unread_news(mocker)
        interaction = _interaction(task, confirm=True)
        task.state = MagicMock()
        task.state.tasks = {"some-other-task": MagicMock(last_news_prompt=datetime.now())}

        assert task._handle_unread_news_prompt() == (True, "", None)
        interaction.confirm.assert_called_once()

    def test_prompts_when_unread_news_is_detected(self, task: SystemUpdateTask, mocker):
        """Unread news -> interact via the injected interaction port."""
        _unread_news(mocker)
        interaction = _interaction(task, confirm=False)

        should_run, reason, skip_reason = task._handle_unread_news_prompt()

        interaction.confirm.assert_called_once()
        assert should_run is False
        assert skip_reason == SkipReason.USER_CANCELLED
        assert "declined" in reason.lower()

    def test_proceeds_on_acknowledge(self, task: SystemUpdateTask, mocker):
        """Unread news plus an accepted acknowledgement -> proceed and record the prompt."""
        _unread_news(mocker)
        interaction = _interaction(task, confirm=True)

        assert task._handle_unread_news_prompt() == (True, "", None)
        interaction.confirm.assert_called_once()

    def test_skips_prompt_within_cooldown(self, task: SystemUpdateTask, mocker):
        """No prompt is shown while the last acknowledgement is still in its cooldown window."""
        _unread_news(mocker)
        interaction = _interaction(task, confirm=True)
        _prompted_at(task, datetime.now())

        assert task._handle_unread_news_prompt() == (True, "", None)
        interaction.confirm.assert_not_called()

    def test_reprompts_after_cooldown_expired(self, task: SystemUpdateTask, mocker):
        _unread_news(mocker)
        interaction = _interaction(task, confirm=True)
        _prompted_at(task, datetime.now() - timedelta(minutes=31))

        assert task._handle_unread_news_prompt() == (True, "", None)
        interaction.confirm.assert_called_once()

    def test_records_prompt_timestamp_on_any_answer(self, task: SystemUpdateTask, mocker):
        """Prompt timestamp is recorded whether the user accepts or declines."""
        _unread_news(mocker)
        _interaction(task, confirm=False)
        state = _prompted_at(task, datetime.now() - timedelta(minutes=31))

        task._handle_unread_news_prompt()

        state.set_task_news_prompt.assert_called_once_with("system-update")

    def test_prompts_when_never_prompted_before(self, task: SystemUpdateTask, mocker):
        """
        `last_news_prompt is None` means the user has never been asked, so the cooldown
        does not apply — the very first run with unread news must prompt.
        """
        _unread_news(mocker)
        interaction = _interaction(task, confirm=True)
        _prompted_at(task, None)

        assert task._handle_unread_news_prompt() == (True, "", None)

        interaction.confirm.assert_called_once()

    def test_shows_the_headlines_when_they_are_available(self, task: SystemUpdateTask, mocker):
        """The prompt must surface actual headlines, not just a bare yes/no question."""
        mocker.patch(f"{_MODULE}.has_unread_arch_news", return_value=True)
        mocker.patch(
            f"{_MODULE}.fetch_arch_news_headlines",
            return_value=["glibc 2.41 requires manual intervention"],
        )
        interaction = _interaction(task, confirm=False)
        _prompted_at(task, None)

        should_run, _, skip_reason = task._handle_unread_news_prompt()

        assert should_run is False
        assert skip_reason == SkipReason.USER_CANCELLED
        prompt = interaction.confirm.call_args.args[0]
        assert "glibc 2.41 requires manual intervention" in prompt
        assert "Proceed with the system update anyway?" in prompt

    def test_prompts_without_headlines_when_the_list_is_empty(self, task: SystemUpdateTask, mocker):
        """No parseable headlines must not blank the prompt: the generic wording still applies."""
        _unread_news(mocker)
        interaction = _interaction(task, confirm=True)
        _prompted_at(task, None)

        assert task._handle_unread_news_prompt() == (True, "", None)

        prompt = interaction.confirm.call_args.args[0]
        assert "There are unread Arch Linux news items." in prompt


class TestShouldSkipPrompt:
    """
    `_should_skip_prompt()` — the cooldown half of the news gate.

    It exists so the prompt is asked at most once per `news_acknowledge_cooldown_minutes` window;
    a `state` of `None` (unit tests, programmatic callers) means there is nothing to remember,
    so the cooldown cannot apply and the prompt must always be shown.
    """

    def test_no_state_means_no_cooldown(self, task: SystemUpdateTask):
        assert task.state is None
        assert task._should_skip_prompt() is False

    def test_unknown_task_name_means_no_cooldown(self, task: SystemUpdateTask):
        task.state = MagicMock(tasks={})

        assert task._should_skip_prompt() is False

    def test_never_prompted_means_no_cooldown(self, task: SystemUpdateTask):
        task.state = MagicMock()
        task.state.tasks = {"system-update": MagicMock(last_news_prompt=None)}

        assert task._should_skip_prompt() is False

    def test_recent_prompt_is_inside_the_window(self, task: SystemUpdateTask):
        _prompted_at(task, datetime.now())

        assert task._should_skip_prompt() is True

    def test_expired_prompt_leaves_the_window(self, task: SystemUpdateTask):
        _prompted_at(task, datetime.now() - timedelta(minutes=31))

        assert task._should_skip_prompt() is False

    def test_zero_cooldown_never_suppresses_the_prompt(self, task: SystemUpdateTask):
        """A cooldown of 0 is the opt-out: the user is asked every single run."""
        task.settings.system_update.news_acknowledge_cooldown_minutes = 0
        _prompted_at(task, datetime.now())

        assert task._should_skip_prompt() is False


class TestRecordNewsPrompt:
    """`_record_news_prompt()` — stamps the cooldown start into state, when state exists."""

    def test_stamps_the_task_name(self, task: SystemUpdateTask):
        task.state = MagicMock()

        task._record_news_prompt()
        task.state.set_task_news_prompt.assert_called_once_with("system-update")

    def test_no_state_is_not_an_error(self, task: SystemUpdateTask):
        """A stateless caller must not crash the gate — it only loses the cooldown."""
        assert task.state is None
        task._record_news_prompt()  # must not raise


class TestExecuteHappyPath:
    @pytest.mark.usefixtures("transaction")
    def test_returns_success_with_populated_details(self, task: SystemUpdateTask):
        result = task.execute()
        details = result.details

        assert result.is_success()
        assert details is not None
        assert details.repo_updates_count == REPO_UPDATE_COUNT
        assert details.aur_updates_count == AUR_UPDATE_COUNT
        assert details.packages_upgraded == ["pkg0", "pkg1", "pkg2"]
        assert details.aur_packages_upgraded == ["pkg0", "pkg1"]
        assert details.aur_packages_failed == []
        assert details.packages_removed == REMOVED_PACKAGES
        assert details.pacnew_files == PACNEW_FILES
        # No snapshot tooling detected and no cache cleanup yet (a later task owns that).
        assert details.pre_update_snapshot_id is None
        assert details.cache_freed_bytes is None

    @pytest.mark.usefixtures("transaction")
    def test_stores_backup_and_manifest_on_the_task(self, task: SystemUpdateTask):
        """Both artifacts are kept on the instance so rollback()/recover can reach them."""
        task.execute()

        assert task.sync_db_backup is not None
        assert task.manifest_before is not None

    @pytest.mark.usefixtures("transaction")
    def test_writes_both_manifests_under_recovery_dir(self, task: SystemUpdateTask):
        task.execute()

        manifests = task.settings.recovery_dir / "manifests"
        assert len(list(manifests.glob("before_*.txt"))) == 1
        assert len(list(manifests.glob("after_*.txt"))) == 1

    def test_pauses_progress_around_all_transactions(
        self, task: SystemUpdateTask, transaction: _Wiring
    ):
        """
        Every sudo-touching call in `execute()` needs the progress rendering paused so its
        password prompt can reach the terminal: pacman, paru, `backup_sync_db`, and the
        snapper lookup for the pre-upgrade snapshot id. Tooling detection is forced on so
        the snapper branch actually runs and its pause is counted.
        """
        transaction.override("detect_btrfs_snapshot_tooling", return_value=True)

        task.execute()

        assert transaction.progress.pause.call_count == PAUSE_COUNT

    def test_advances_progress_once_per_step(self, task: SystemUpdateTask, transaction: _Wiring):
        """
        `advance` fires once per `report_progress`, and the counts differ by design.

        `_STEP_COUNT` describes the transaction's phases, but only seven of them are announced:
        the pre-flight update query has no UI to advance through — it is silent setup — and
        the opening `progress.start()` is the start of the bar, not a completed step. So
        `ANNOUNCED_STEPS + 2 == _STEP_COUNT`; the two unannounced phases are the only gap.
        """
        task.execute()

        assert transaction.progress.advance.call_count == ANNOUNCED_STEPS
        assert ANNOUNCED_STEPS + 2 == task._STEP_COUNT

    def test_calls_the_utilities_in_transaction_order(
        self, task: SystemUpdateTask, transaction: _Wiring
    ):
        """
        The order is the safety contract: manifest, then backup, then anything destructive.

        Snapshotting before the backup, and running pacman only after both, is what makes a
        failure recoverable. Reordering these calls would still satisfy every other assertion
        in this class, so the sequence is pinned explicitly.

        `snapshot_package_manifest` appears twice on purpose — once before the transaction and
        once after — and the diff sits strictly between the second snapshot and nothing else,
        because it compares the two files the snapshots produced.

        Each stub's original `side_effect`/`return_value` is captured first and replayed from
        inside the recorder, so ordering is observed without changing what any helper returns.
        """
        order: list[str] = []
        watched = (
            "snapshot_package_manifest",
            "backup_sync_db",
            "run_system_upgrade",
            "detect_btrfs_snapshot_tooling",
            "run_aur_upgrade",
            "diff_manifests",
        )
        original = {
            name: (transaction.mocks[name].side_effect, transaction.mocks[name].return_value)
            for name in watched
        }

        def _recorder(name: str):
            effect, value = original[name]

            def _record(*args, **kwargs):
                order.append(name)
                return effect(*args, **kwargs) if effect is not None else value

            return _record

        for name in watched:
            transaction.mocks[name].side_effect = _recorder(name)

        task.execute()

        assert order == [
            "snapshot_package_manifest",
            "backup_sync_db",
            "run_system_upgrade",
            "detect_btrfs_snapshot_tooling",
            "run_aur_upgrade",
            "snapshot_package_manifest",
            "diff_manifests",
        ]


class TestExecuteFailurePaths:
    def test_backup_failure_returns_failed_without_upgrading(
        self, task: SystemUpdateTask, transaction: _Wiring
    ):
        """No safety net, no transaction — failing closed is the whole point of the backup."""
        transaction.override("backup_sync_db", side_effect=OSError("disk full"))

        result = task.execute()

        assert result.is_failed()
        assert transaction.mocks["run_system_upgrade"].call_count == 0
        assert not task.recovery_file.exists()

    def test_pacman_failure_raises_for_rollback(self, task: SystemUpdateTask, transaction: _Wiring):
        """
        A pacman abort must reach `BaseTask.run()` as an exception, not a FAILED result.

        Returning a result would skip rollback entirely — the sync database was already
        refreshed by the failed transaction, so restoring it is the only thing that matters.
        """
        transaction.override("run_system_upgrade", return_value=_fail(returncode=1))

        with pytest.raises(RuntimeError, match="exit code 1"):
            task.execute()

        assert transaction.mocks["run_aur_upgrade"].call_count == 0
        assert not task.recovery_file.exists()

    def test_aur_failure_returns_partial_and_lists_pending_aur_as_failed(
        self, task: SystemUpdateTask, transaction: _Wiring
    ):
        """An AUR build failure says nothing about the pacman sync database, so it is partial."""
        transaction.override("run_aur_upgrade", return_value=_fail(returncode=1))

        result = task.execute()
        details = result.details

        assert result.is_partial()
        assert details is not None
        assert details.aur_packages_failed == ["pkg0", "pkg1"]
        assert details.aur_packages_upgraded == []
        # The repository half still completed, so its packages remain reported as upgraded.
        assert details.packages_upgraded == ["pkg0", "pkg1", "pkg2"]

    def test_aur_failure_still_writes_recovery_record(
        self, task: SystemUpdateTask, transaction: _Wiring
    ):
        transaction.override("run_aur_upgrade", return_value=_fail(returncode=1))

        task.execute()

        assert task.recovery_file.exists()


class TestSnapshotRecording:
    def test_records_snapshot_id_when_tooling_present(
        self, task: SystemUpdateTask, transaction: _Wiring
    ):
        """snap-pac creates a `pre` snapshot just before pacman runs, so that number is the
        rollback target for the upgrade that just happened."""
        transaction.override("detect_btrfs_snapshot_tooling", return_value=True)
        transaction.override("get_latest_snapshot_id", return_value=SNAPSHOT_ID)

        result = task.execute()

        assert result.details is not None
        assert result.details.pre_update_snapshot_id == SNAPSHOT_ID
        assert task.pre_update_snapshot_id == SNAPSHOT_ID

    def test_no_snapshot_lookup_when_tooling_absent(
        self, task: SystemUpdateTask, transaction: _Wiring
    ):
        """Querying snapper without snap-pac installed would just shell out for nothing."""
        result = task.execute()

        assert result.details is not None
        assert transaction.mocks["get_latest_snapshot_id"].call_count == 0
        assert result.details.pre_update_snapshot_id is None


class TestRecoveryRecord:
    @pytest.mark.usefixtures("transaction")
    def test_record_has_exactly_the_documented_key_set(self, task: SystemUpdateTask):
        """
        The recovery record is a contract with `archcare task recover` and with the user.

        A key added here without a consumer, or `updated_at` dropped, would break the manual
        recovery path while every field-level assertion below still passed. Pin the set itself,
        not just the values.
        """
        task.execute()

        record = json.loads(task.recovery_file.read_text(encoding="utf-8"))

        assert set(record) == {
            "task",
            "updated_at",
            "sync_db_backup",
            "manifest_before",
            "manifest_after",
            "pre_update_snapshot_id",
            "packages_upgraded",
            "aur_packages_upgraded",
            "aur_packages_failed",
            "packages_removed",
        }
        datetime.fromisoformat(record["updated_at"])

    @pytest.mark.usefixtures("transaction")
    def test_records_artifact_paths_and_outcome(self, task: SystemUpdateTask):
        task.execute()

        record = json.loads(task.recovery_file.read_text(encoding="utf-8"))

        assert record["task"] == "system-update"
        assert record["sync_db_backup"] == str(task.sync_db_backup)
        assert record["manifest_before"] == str(task.manifest_before)
        assert record["manifest_after"].endswith(".txt")
        assert record["pre_update_snapshot_id"] is None
        assert record["packages_removed"] == REMOVED_PACKAGES
        assert record["packages_upgraded"] == ["pkg0", "pkg1", "pkg2"]

    def test_record_is_valid_json_after_aur_failure(
        self, task: SystemUpdateTask, transaction: _Wiring
    ):
        """A partial run is exactly when a user will go looking for the record."""
        transaction.override("run_aur_upgrade", return_value=_fail(returncode=1))

        task.execute()

        record = json.loads(task.recovery_file.read_text(encoding="utf-8"))
        assert record["aur_packages_failed"] == ["pkg0", "pkg1"]

    @pytest.mark.usefixtures("transaction")
    def test_overwrites_a_previous_record(self, task: SystemUpdateTask):
        """`archcare task recover system-update` reads one file, so a stale record left behind
        by an older run would point at the wrong manifests and rollback target."""
        task.recovery_file.parent.mkdir(parents=True, exist_ok=True)
        task.recovery_file.write_text('{"packages_upgraded": ["stale"]}', encoding="utf-8")

        task.execute()

        assert "stale" not in task.recovery_file.read_text(encoding="utf-8")

    @pytest.mark.usefixtures("transaction")
    def test_creates_the_recovery_directory_if_absent(self, task: SystemUpdateTask):
        assert not task.settings.recovery_dir.exists()

        task.execute()

        assert task.settings.recovery_dir.is_dir()


class TestRollback:
    """`rollback()` is the only automatic recovery this task has, so it must never throw."""

    def test_restores_the_sync_db_from_the_backup(
        self, task: SystemUpdateTask, transaction: _Wiring
    ):
        """
        The backup taken in `execute()` is the restore point — and nothing else is passed.

        Asserting on `call_args` rather than `call_count` pins *which* backup is used: a
        rollback against a stale or freshly-named path would restore the wrong state while
        every count-based assertion still passed.
        """
        task.execute()

        task.rollback()

        transaction.mocks["restore_sync_db"].assert_called_once_with(task.sync_db_backup)

    def test_no_backup_logs_and_does_not_restore(
        self, task: SystemUpdateTask, transaction: _Wiring
    ):
        """
        No backup means nothing to rewind, and that is not an error worth raising.

        `execute()` returns a failure when the backup itself fails, but another caller may
        raise before that point; a rollback with nothing to restore must be a no-op.
        """
        task.sync_db_backup = None

        task.rollback()

        assert transaction.mocks["restore_sync_db"].call_count == 0

    def test_restore_failure_is_swallowed(self, task: SystemUpdateTask, transaction: _Wiring):
        """A failed restore is a manual-recovery situation, not a crash."""
        task.sync_db_backup = Path("/tmp/sync-db-backup")
        transaction.override("restore_sync_db", side_effect=OSError("disk gone"))

        task.rollback()  # must not raise

    def test_restore_failure_does_not_mask_the_transaction_error(
        self, task: SystemUpdateTask, transaction: _Wiring
    ):
        """
        Through `run()`: a pacman failure must still read as a pacman failure.

        Tested at the template-method level rather than by calling `rollback()` directly —
        the property under test belongs to `BaseTask.run()`'s sequencing, not to the method
        in isolation.

        The threshold is lowered because `run()` evaluates `should_run()` first: the fixture
        reports only 3 pending repository updates, which is below the default 30 and would
        skip before the transaction ever ran.
        """
        task.settings.system_update.min_repo_updates_threshold = 0
        transaction.override("run_system_upgrade", return_value=_fail())

        result = task.run()

        assert result.is_failed()
        assert "pacman -Syu" in result.message
        assert transaction.mocks["restore_sync_db"].call_count == 1

    def test_a_restore_failure_still_yields_a_pacman_failure(
        self, task: SystemUpdateTask, transaction: _Wiring
    ):
        """
        The negative control: a broken restore must not become the reported error.

        If `rollback()` propagated, the user's terminal would blame the restore instead of
        `pacman -Syu` — the one thing they need to act on.
        """
        task.settings.system_update.min_repo_updates_threshold = 0
        transaction.override("run_system_upgrade", return_value=_fail())
        transaction.override("restore_sync_db", side_effect=OSError("disk gone"))

        result = task.run()

        assert result.is_failed()
        assert "pacman -Syu" in result.message
        assert "disk gone" not in result.message


class TestPostExecute:
    def test_successful_run_triggers_cache_cleanup(
        self, task: SystemUpdateTask, transaction: _Wiring
    ):
        """
        The retention values must come from settings, not from a hardcoded default.

        `cache_keep_versions` is the user's downgrade depth: a hardcoded value would silently
        purge more history than the configuration allows.
        """
        result = success("done", details=SystemUpdateDetails())

        task.post_execute(result)

        transaction.mocks["clean_cache"].assert_called_once_with(
            keep=task.settings.system_update.cache_keep_versions,
            keep_uninstalled=task.settings.system_update.cache_keep_uninstalled_versions,
        )

    def test_honours_custom_retention_settings(self, task: SystemUpdateTask, transaction: _Wiring):
        task.settings.system_update.cache_keep_versions = 5
        task.settings.system_update.cache_keep_uninstalled_versions = 1

        task.post_execute(success("done", details=SystemUpdateDetails()))

        transaction.mocks["clean_cache"].assert_called_once_with(keep=5, keep_uninstalled=1)

    def test_stamps_the_reclaimed_bytes_on_the_result(
        self, task: SystemUpdateTask, transaction: _Wiring
    ):
        """`SystemUpdateDetails` is frozen, so this must be a replacement, not an assignment."""
        transaction.override("clean_cache", return_value=CACHE_FREED_BYTES)
        result = success("done", details=SystemUpdateDetails())
        original = result.details
        assert original is not None

        task.post_execute(result)

        assert original is not result.details
        assert original.cache_freed_bytes is None
        assert result.details is not None
        assert result.details.cache_freed_bytes == CACHE_FREED_BYTES

    def test_a_failed_run_skips_cache_cleanup(self, task: SystemUpdateTask, transaction: _Wiring):
        """Pruning after a failure would destroy the downgrade path a user may need."""
        task.post_execute(failed("boom", error="boom"))

        assert transaction.mocks["clean_cache"].call_count == 0

    def test_a_partial_run_skips_cache_cleanup(self, task: SystemUpdateTask, transaction: _Wiring):
        """Deliberate: see the reasoning in `post_execute()`. Partial means the AUR half broke."""
        task.post_execute(partial("half done", details=SystemUpdateDetails()))

        assert transaction.mocks["clean_cache"].call_count == 0

    def test_cleanup_failure_is_swallowed(self, task: SystemUpdateTask, transaction: _Wiring):
        """`run()` calls `post_execute()` inside its `try`; a raise would trigger `rollback()`."""
        transaction.override("clean_cache", side_effect=OSError("cache busy"))

        task.post_execute(success("done", details=SystemUpdateDetails()))  # must not raise

    @pytest.mark.usefixtures("transaction")
    def test_post_execute_is_a_noop_without_an_interaction_port(
        self, system_update_config: TaskConfig, system_update_settings: AppSettings
    ):
        """Non-interactive runs (tests, `archcare task status`) have no port to notify through."""
        task = SystemUpdateTask(config=system_update_config, settings=system_update_settings)

        task.post_execute(success("done", details=SystemUpdateDetails()))  # must not raise

    @pytest.mark.usefixtures("transaction")
    def test_a_failing_notify_is_swallowed(
        self, system_update_config: TaskConfig, system_update_settings: AppSettings
    ):
        """
        A broken notification backend must not fail a run that already upgraded the system.

        `post_execute()` runs inside `run()`'s `try` block, so a raise here would be caught,
        routed to `rollback()`, and report a good upgrade as a failure.

        Requests `transaction` for its side effect: without it the real `clean_cache` runs
        and shells out to `sudo paccache` on the developer's machine.
        """
        manager = MagicMock()
        manager.send_task_result_notification.side_effect = OSError("no dbus")
        task = SystemUpdateTask(
            config=system_update_config,
            settings=system_update_settings,
            deps=TaskDependencies(notification_manager=manager),
        )

        task.post_execute(failed("boom", error="boom"))  # must not raise

    @pytest.mark.usefixtures("transaction")
    def test_a_completed_run_is_announced(self, task: SystemUpdateTask):
        """
        A successful upgrade is worth a desktop notification: it is long and manual.

        Requests `transaction`: this result is a success, so without the fixture the real
        `clean_cache` would run `sudo paccache` for real.
        """
        manager = MagicMock()
        task.notification_manager = manager

        task.post_execute(success("Upgraded 3 packages", details=SystemUpdateDetails()))

        manager.send_task_result_notification.assert_called_once_with(
            task_name=task.name,
            success=True,
            message="Upgraded 3 packages",
        )

    @pytest.mark.usefixtures("transaction")
    def test_a_backup_failure_run_is_announced(self, task: SystemUpdateTask):
        """
        A failed run is the case that matters most — the user needs to know it happened.

        Requests `transaction` so a future edit that widens the cleanup gate cannot turn
        this into a real `sudo paccache` call.
        """
        manager = MagicMock()
        task.notification_manager = manager

        task.post_execute(failed("Failed to back up the pacman sync database: disk full"))

        manager.send_task_result_notification.assert_called_once_with(
            task_name=task.name,
            success=False,
            message="Failed to back up the pacman sync database: disk full",
        )


# ---------------------------------------------------------------------------
# Prompt guard tests
# ---------------------------------------------------------------------------


class TestEveryGuardedLaunchRunsWhilePaused:
    """
    Every guarded launch must run with the display not live — system-update pre-warms
    nothing, so the fail-fast router raises at the moment any live launch happens (cold
    sudo work, or `paru -Sua` meeting a render). Passing means a full `execute()` +
    `post_execute()` (+ `rollback()`) never tripped it. The guard lives in conftest.py.
    """

    @pytest.fixture
    def task_deps(self, prompt_guard: PromptGuardLedger) -> Iterator[TaskDependencies]:
        """
        Class-scoped override: tasks under the guard receive progress via `TaskDependencies`.

        Teardown stops the render (`run()`'s finally never runs for direct-execute tests)
        and re-asserts the ledger, because `post_execute()`/`rollback()` deliberately
        swallow `Exception` — a guard raise caught there would otherwise pass silently.
        """
        progress = bind_guard_progress(prompt_guard)
        yield TaskDependencies(progress=progress)
        progress.stop()
        assert not prompt_guard.violations, f"prompt-guard violations: {prompt_guard.violations}"

    # First argv tokens each documented helper produces on a fully-successful `execute()` +
    # `post_execute()` pass. An alarm-if-vacuous control rather than the invariant itself: a token
    # disappearing means the recorder stopped seeing that helper.
    EXPECTED_GUARDED_TOOLS = frozenset({"cp", "pacman", "snapper", "paccache", "paru"})

    def test_task_drives_the_guard_bound_adapter(
        self, task: SystemUpdateTask, prompt_guard: PromptGuardLedger
    ):
        """The bundle must deliver the bound adapter itself — the guard reads `is_live` off it."""
        assert task.progress is prompt_guard.progress

    def test_execute_and_post_execute_pause_around_every_guarded_launch(
        self, task: SystemUpdateTask, prompt_guard: PromptGuardLedger
    ):
        """Run the full flow: a violating launch raises inside the router at that call."""
        result = task.execute()
        task.post_execute(result)

        assert prompt_guard.guarded_calls, "recorder saw no guarded traffic; harness is vacuous"

    def test_the_guard_observes_all_documented_helpers(
        self, task: SystemUpdateTask, prompt_guard: PromptGuardLedger
    ):
        """Negative control: the recorder must actually see the documented traffic."""
        result = task.execute()
        task.post_execute(result)

        seen = prompt_guard.first_tokens()
        assert prompt_guard.guarded_calls, "recorder saw no guarded traffic; harness is vacuous"
        missing = self.EXPECTED_GUARDED_TOOLS - seen
        assert not missing, f"documented helpers never observed: {missing}"

    def test_rollback_restores_the_sync_db_under_pause(
        self, task: SystemUpdateTask, prompt_guard: PromptGuardLedger, tmp_path: Path
    ):
        """The failure path reaches sudo too, through `restore_sync_db` — same guard."""
        backup = tmp_path / "sync-db" / "sync-db_2026-01-01_000000"
        backup.mkdir(parents=True)
        task.sync_db_backup = backup
        # Production reaches rollback only after execute() raised with the bar already up
        # (`run()` stops it in its finally), so the render must be live here too.
        task.progress.start(total=1)

        task.rollback()

        assert "cp" in prompt_guard.first_tokens()
