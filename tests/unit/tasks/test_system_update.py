"""
Unit tests for SystemUpdateTask (tasks/system_update.py).

Scope: All of the task-specific logic that genuinely deserve its own
unit tests, not a re-verification of the base task's behavior.
"""

import json
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime
from os.path import expanduser
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from _pytest.monkeypatch import MonkeyPatch

from archcare.config import AppSettings, SkipReason, TaskConfig
from archcare.core import SystemUpdateDetails
from archcare.core.models import failed, partial, success
from archcare.core.progress import TaskProgress
from archcare.tasks.system_update import SystemUpdateTask
from archcare.utils import PackageUpdateInfo
from archcare.utils.system import CommandResult

_MODULE = "archcare.tasks.system_update"

# Fixed shape of the transaction the `transaction` fixture fakes, asserted by name so the
# expected values are stated once instead of repeated as bare literals in every test.
REPO_UPDATE_COUNT = 3
AUR_UPDATE_COUNT = 2
TRANSACTION_COUNT = 2
PAUSE_COUNT = 3  # pacman + paru + backup_sync_db (all need sudo, so all need pause)
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
def task(system_update_config: TaskConfig, system_update_settings: AppSettings) -> SystemUpdateTask:
    return SystemUpdateTask(config=system_update_config, settings=system_update_settings)


def _block_all(mocker, *, terminal=True, unread_news=False) -> None:
    """Neutralise the three pre_check() lookups so a test can isolate one of them."""
    mocker.patch(f"{_MODULE}.check_command_exists", return_value=True)
    mocker.patch(f"{_MODULE}.has_interactive_terminal", return_value=terminal)
    mocker.patch(f"{_MODULE}.has_unread_arch_news", return_value=unread_news)


def _updates(count: int) -> list[PackageUpdateInfo]:
    """Build `count` distinct pending-update entries."""
    return [
        PackageUpdateInfo(name=f"pkg{i}", old_version="1.0-1", new_version="2.0-1")
        for i in range(count)
    ]


def _ok(command: str = "mock") -> CommandResult:
    """A successful `CommandResult`.

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
    """A progress port that records `advance`/`pause` calls and stays a working context manager.

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
    """Handles for the OS-boundary stubs installed by the `transaction` fixture.

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
    """Wire every OS boundary `execute()` touches, so the transaction runs fully in memory.

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
        "run_system_upgrade": {"return_value": _ok()},
        "run_aur_upgrade": {"return_value": _ok()},
        "detect_btrfs_snapshot_tooling": {"return_value": False},
        "diff_manifests": {"return_value": REMOVED_PACKAGES},
        "list_pacnew_files": {"return_value": PACNEW_FILES},
    }
    mocks = {name: mocker.patch(f"{_MODULE}.{name}", **kwargs) for name, kwargs in stubs.items()}

    task.progress = mock_progress
    return _Wiring(patch=mocker.patch, mocks=mocks, progress=mock_progress)


class TestPreCheckCommands:
    def test_missing_pacman_blocks_with_arch_wiki_guide(self, mocker, task: SystemUpdateTask):
        mocker.patch(f"{_MODULE}.check_command_exists", return_value=False)

        can_run, reason = task.pre_check()

        assert can_run is False
        assert "Arch wiki" in reason
        assert "https://wiki.archlinux.org/" in reason

    @pytest.mark.parametrize(
        ("missing", "package"),
        [("paru", "paru"), ("checkupdates", "pacman-contrib")],
    )
    def test_missing_command_blocks_with_install_hint(
        self, task: SystemUpdateTask, mocker, missing, package
    ):
        """Each command's install hint must name the package that actually provides it.

        `checkupdates` ships in `pacman-contrib`, not `paru` — a copy-paste slip in the
        pairing would tell the user to install something they already have.
        """
        mocker.patch(
            f"{_MODULE}.check_command_exists",
            side_effect=lambda cmd: cmd != missing,
        )
        mocker.patch(f"{_MODULE}.has_interactive_terminal", return_value=True)
        mocker.patch(f"{_MODULE}.has_unread_arch_news", return_value=False)

        can_run, reason = task.pre_check()

        assert can_run is False
        assert missing in reason
        assert f"sudo pacman -S {package}" in reason


class TestPreCheckTerminal:
    def test_missing_terminal_blocks(self, task: SystemUpdateTask, mocker):
        _block_all(mocker, terminal=False)

        can_run, reason = task.pre_check()

        assert can_run is False
        assert "interactive terminal" in reason

    def test_terminal_is_checked_before_news(self, task: SystemUpdateTask, mocker):
        """A missing terminal is the more fundamental blocker; report it first."""
        _block_all(mocker, terminal=False, unread_news=True)

        can_run, reason = task.pre_check()

        assert can_run is False
        assert "interactive terminal" in reason
        assert "news" not in reason


class TestPreCheckArchNews:
    def test_unread_news_blocks(self, task: SystemUpdateTask, mocker):
        _block_all(mocker, unread_news=True)

        can_run, reason = task.pre_check()

        assert can_run is False
        assert "Unread Arch Linux news" in reason

    def test_read_news_passes(self, task: SystemUpdateTask, mocker):
        _block_all(mocker, unread_news=False)

        assert task.pre_check() == (True, "")


class TestRecoveryFilePath:
    def test_is_under_recovery_dir(self, task: SystemUpdateTask):
        assert task.recovery_file == task.settings.recovery_dir / "system-update.json"


class TestHomeIsolation:
    """Guards against this module ever writing into the developer's real home.

    `run()` creates a log file at `settings.log_dir/tasks/<name>.log`. If the
    `Path.home` redirect in `system_update_settings` is ever dropped, weakened, or defeated by the
    `SUDO_USER` indirection in the `AppSettings.home_dir` indirection, the file silently lands in
    `~/.local/state/archcare/logs/tasks/` — the test still passes, so nothing else would
    catch it. These assertions fail loudly instead.

    Every test here requests `transaction` so the whole transaction runs against the 13 stubs
    rather than patching the handful of names this class happened to need. A test that lists its
    own patches instead inherits the escape: it predates the real `execute()`, so patching only
    `get_pending_repo_updates` left `get_pending_aur_updates`, `snapshot_package_manifest` and
    `backup_sync_db` live, which copied the developer's real `/var/lib/pacman/sync` into a temp
    dir and put a `sudo` prompt on their terminal. Requesting the shared fixture is the structural
    fix: a helper added to `execute()` later is stubbed here automatically.
    """

    @staticmethod
    def _real_home_tasks_log() -> Path:
        """The real `~/.local/state/archcare/logs/tasks`, independent of the fixture.

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
        assert not real_log.exists(), (
            "a stale system-update.log in the real home means an earlier run escaped the "
            "tmp_path redirect; delete it and fix the redirect before trusting this suite"
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


class TestShouldRun:
    def test_skips_below_threshold(self, task: SystemUpdateTask, mocker):
        mocker.patch(f"{_MODULE}.get_pending_repo_updates", return_value=_updates(4))

        should_run, reason, skip_reason = task.should_run()

        assert should_run is False
        assert skip_reason is SkipReason.NO_WORK_NEEDED
        assert "4" in reason
        assert "30" in reason

    def test_skips_when_one_below_threshold(self, task: SystemUpdateTask, mocker):
        mocker.patch(f"{_MODULE}.get_pending_repo_updates", return_value=_updates(29))

        should_run, _, _ = task.should_run()

        assert should_run is False

    def test_runs_at_exactly_the_threshold(self, task: SystemUpdateTask, mocker):
        """30 pending updates meets the default threshold of 30: the boundary is inclusive."""
        mocker.patch(f"{_MODULE}.get_pending_repo_updates", return_value=_updates(30))

        assert task.should_run() == (True, "", None)

    def test_runs_above_threshold(self, task: SystemUpdateTask, mocker):
        mocker.patch(f"{_MODULE}.get_pending_repo_updates", return_value=_updates(45))

        assert task.should_run() == (True, "", None)

    def test_runs_with_zero_pending_when_threshold_is_zero(self, task: SystemUpdateTask, mocker):
        """A user who sets the threshold to 0 opts into updating on every run."""
        mocker.patch(f"{_MODULE}.get_pending_repo_updates", return_value=[])
        task.settings.system_update.min_repo_updates_threshold = 0

        assert task.should_run() == (True, "", None)

    def test_honours_a_custom_threshold(self, system_update_config: TaskConfig, mocker):
        settings = AppSettings(user=None)
        settings.system_update.min_repo_updates_threshold = 1
        task = SystemUpdateTask(config=system_update_config, settings=settings)
        mocker.patch(f"{_MODULE}.get_pending_repo_updates", return_value=_updates(1))

        assert task.should_run() == (True, "", None)

    def test_skips_with_a_raised_threshold(self, system_update_config: TaskConfig, mocker):
        """Raising the threshold above what is pending must skip, not run."""
        settings = AppSettings(user=None)
        settings.system_update.min_repo_updates_threshold = 200
        task = SystemUpdateTask(config=system_update_config, settings=settings)
        mocker.patch(f"{_MODULE}.get_pending_repo_updates", return_value=_updates(45))

        should_run, reason, skip_reason = task.should_run()

        assert should_run is False
        assert skip_reason is SkipReason.NO_WORK_NEEDED
        assert "200" in reason

    def test_propagates_a_failing_update_query(self, task: SystemUpdateTask, mocker):
        """A broken package manager must surface, not silently skip."""
        mocker.patch(
            f"{_MODULE}.get_pending_repo_updates",
            side_effect=OSError("checkupdates failed (exit 2)"),
        )

        with pytest.raises(OSError, match="checkupdates failed"):
            task.should_run()


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
        Both pacman and paru need the progress rendering to be paused around their transactions due
        to having interactive prompts themselves. `backup_sync_db` also needs to be paused because
        it`s a sudo operation.
        """
        task.execute()

        assert transaction.progress.pause.call_count == PAUSE_COUNT

    def test_advances_progress_once_per_step(self, task: SystemUpdateTask, transaction: _Wiring):
        """`advance` fires once per `report_progress`, and the counts differ by design.

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
        """The order is the safety contract: manifest, then backup, then anything destructive.

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
        """A pacman abort must reach `BaseTask.run()` as an exception, not a FAILED result.

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
        """The recovery record is a contract with `archcare task recover` and with the user.

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
        """The backup taken in `execute()` is the restore point — and nothing else is passed.

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
        """No backup means nothing to rewind, and that is not an error worth raising.

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
        """Through `run()`: a pacman failure must still read as a pacman failure.

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
        """The negative control: a broken restore must not become the reported error.

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
        """The retention values must come from settings, not from a hardcoded default.

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
        """A broken notification backend must not fail a run that already upgraded the system.

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
            notification_manager=manager,
        )

        task.post_execute(failed("boom", error="boom"))  # must not raise

    @pytest.mark.usefixtures("transaction")
    def test_a_completed_run_is_announced(self, task: SystemUpdateTask):
        """A successful upgrade is worth a desktop notification: it is long and manual.

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
        """A failed run is the case that matters most — the user needs to know it happened.

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
