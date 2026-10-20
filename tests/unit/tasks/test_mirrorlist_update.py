"""
Unit tests for MirrorlistUpdateTask (tasks/mirrorlist_update.py), focused on the sudo-bound
choreography the shared guard must certify: `sudo -v` pre-warm *first* → `cp` backup →
`reflector` under the spinner (covered by the pre-warm) → retention `rm` after the display
is gone — plus the failure side of a declined pre-warm (abort before any file exists, so
`rollback()` has nothing to "restore").
"""

import os
import time
from pathlib import Path

import pytest
from _pytest.monkeypatch import MonkeyPatch

from archcare.config import AppSettings, TaskConfig
from archcare.config.models import MirrorlistSettings
from archcare.core import MirrorlistUpdateDetails, success
from archcare.tasks.mirrorlist_update import MirrorlistUpdateTask

from .conftest import PauseAwareProgress, SudoPauseLedger

_MODULE = "archcare.tasks.mirrorlist_update"
_MIRRORLIST_MODULE = "archcare.utils.mirrorlist"

_ORIGINAL_CONTENT = "Server = https://old.slow.mirror.com/$repo/os/$arch\n"
_FAKE_REFLECTED_CONTENT = "Server = https://fast.mocked.mirror.com/$repo/os/$arch\n"

pytestmark = pytest.mark.usefixtures("no_task_logging")


@pytest.fixture
def mirrorlist_config() -> TaskConfig:
    return TaskConfig.model_validate(
        {
            "name": "mirrorlist-update",
            "type": "manual",
            "frequency": 14,
            "description": "Refresh the pacman mirrorlist with reflector",
            "enabled": True,
        }
    )


@pytest.fixture
def task(
    tmp_path: Path, monkeypatch: MonkeyPatch, mirrorlist_config: TaskConfig
) -> MirrorlistUpdateTask:
    """Task pointed at a real (user-owned) sandbox mirrorlist under tmp_path."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    mirrorlist = tmp_path / "etc/pacman.d/mirrorlist"
    mirrorlist.parent.mkdir(parents=True)
    mirrorlist.write_text(_ORIGINAL_CONTENT)
    settings = AppSettings(
        user=None,
        mirrorlist=MirrorlistSettings(path=mirrorlist),
    )
    return MirrorlistUpdateTask(config=mirrorlist_config, settings=settings)


@pytest.fixture
def sudo_guard(
    sudo_pause_ledger: SudoPauseLedger, mocker, task: MirrorlistUpdateTask
) -> SudoPauseLedger:
    """Wire `execute()` and `post_execute()` with only the OS boundary faked.

    The real utils helpers run (info snapshot, backup, validation, retention scan); the
    shared ledger's recorders answer every wrapper call. Only this task's specifics live
    here: `reflector` never runs for real, so a side effect writes a plausible mirrorlist
    to its `--save` path for the *real* validator to consume, and `rm` really unlinks the
    retention targets so the pruning verdict is observable.
    """
    ledger = sudo_pause_ledger

    def _reflector_writes_mirrorlist(argv: tuple[str, ...]) -> None:
        save_idx = argv.index("--save") + 1
        Path(argv[save_idx]).write_text(_FAKE_REFLECTED_CONTENT)

    def _rm_really_unlinks(argv: tuple[str, ...]) -> None:
        # Router passes caller-issued argv with the "sudo" prefix stripped: ("rm", "-f", *paths).
        for raw_path in argv[2:]:
            Path(raw_path).unlink(missing_ok=True)

    ledger.side_effects.update(
        {"reflector": _reflector_writes_mirrorlist, "rm": _rm_really_unlinks}
    )
    mocker.patch(f"{_MODULE}.check_command_exists", return_value=True)
    mocker.patch(f"{_MIRRORLIST_MODULE}.check_command_exists", return_value=True)

    task.progress = PauseAwareProgress(ledger)
    return ledger


class TestSudoChoreography:
    """The guard pins the order and display-state of every sudo-bound call in the flow."""

    def test_execute_pre_warms_before_any_sudo_work(
        self, task: MirrorlistUpdateTask, sudo_guard: SudoPauseLedger
    ):
        """
        The `-v` refresh must be the first sudo call of the run — before the `cp` backup —
        so a declined prompt aborts before any file exists and every later sudo launch rides
        the fresh timestamp.
        """
        result = task.execute()

        assert result.is_success()
        # Recorded argv is sudo-prefixed; compare tokens after the "sudo" entry.
        order = [argv[1] for argv, _ in sudo_guard.sudo_calls]
        assert order == ["-v", "cp", "reflector"], f"unexpected sudo order: {sudo_guard.sudo_calls}"
        assert sudo_guard.unprotected_sudo_calls() == []

    def test_execute_runs_reflector_under_live_display_covered_by_prewarm(
        self, task: MirrorlistUpdateTask, sudo_guard: SudoPauseLedger
    ):
        """
        Reflector keeps its spinner (nondeterministic network phase), so its sudo launch
        legitimately runs against a live display — safe only because the pre-warm came first,
        which the ledger's full-invariant method certifies.
        """
        task.execute()

        reflector_calls = [
            (argv, was_live) for argv, was_live in sudo_guard.sudo_calls if argv[1] == "reflector"
        ]
        assert len(reflector_calls) == 1
        assert reflector_calls[0][1], "reflector must be observed under the live spinner"
        sudo_refreshes = [argv for argv, _ in sudo_guard.sudo_calls if argv[1] == "-v"]
        assert sudo_refreshes, "no pre-warm observed before the live-display launch"
        assert sudo_guard.unprotected_sudo_calls() == []

    def test_declined_prewarm_aborts_before_the_backup(
        self, task: MirrorlistUpdateTask, sudo_guard: SudoPauseLedger, mocker
    ):
        """Regression: a declined `sudo -v` must raise before `backup_file` — otherwise
        `rollback()` finds a backup of an unmodified mirrorlist and re-prompts with cold
        credentials, ending in a false 'mirrorlist may be broken' critical."""
        mocker.patch(f"{_MODULE}.ensure_sudo_credentials", return_value=False)

        with pytest.raises(RuntimeError, match="Could not obtain sudo credentials"):
            task.execute()

        assert task.backup_path is None
        assert sudo_guard.sudo_calls == [], "no sudo traffic may follow a declined pre-warm"
        assert _ORIGINAL_CONTENT in task.mirrorlist_path.read_text()

    def test_post_execute_prunes_through_sudo_rm_with_display_down(
        self, task: MirrorlistUpdateTask, sudo_guard: SudoPauseLedger
    ):
        """
        Retention deletes root-owned backups via `sudo rm` (a plain unlink would hit
        PermissionError on the root-owned parent), and it runs after the display is gone.
        """
        backup_dir = task.mirrorlist_path.parent
        backup = Path(f"{task.mirrorlist_path}_2026-01-01_000000.backup")
        backup.write_text(_ORIGINAL_CONTENT)
        task.backup_path = backup
        for i in range(1, 7):  # 6 staggered old backups
            old_backup = backup_dir / f"mirrorlist_2026-01-0{i}_120000.backup"
            old_backup.write_text(f"Old backup {i}")
            # i=1..5 already older than the fresh backup; keep ties impossible
            past = time.time() - (100 - i) * 60
            os.utime(old_backup, (past, past))
        os.utime(backup, (time.time(), time.time()))

        task.post_execute(success("OK", details=MirrorlistUpdateDetails()))

        # 7 backups totaled (task backup + 6 old); retention 5 → the two oldest go.
        rm_calls = [(argv, was_live) for argv, was_live in sudo_guard.sudo_calls if argv[1] == "rm"]
        assert len(rm_calls) == 1, f"expected one rm batch, got {sudo_guard.sudo_calls}"
        argv, live = rm_calls[0]
        assert not live, "retention must run with the display not live"
        # argv = ("sudo", "rm", "-f", *paths)
        assert set(argv[3:]) == {
            str(backup_dir / "mirrorlist_2026-01-01_120000.backup"),
            str(backup_dir / "mirrorlist_2026-01-02_120000.backup"),
        }
        assert sudo_guard.unprotected_sudo_calls() == []
