"""
Integration tests for system-update task (`task run` and `task recover`).

Real CLI invocation, real AppContext/config I/O, real task
orchestration — only the actual subprocess / OS boundary is mocked.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from archcare.cli.app import app
from archcare.utils.info_models import PackageUpdateInfo
from archcare.utils.system import CommandResult

runner = CliRunner()

_MODULE = "archcare.tasks.system_update"
_SYSTEM_MODULE = "archcare.utils.system"
_PACMAN_MODULE = "archcare.utils.pacman"

# System-update has 7 announced progress steps (ANNOUNCED_STEPS in unit tests)
STEP_COUNT = 9  # _STEP_COUNT in SystemUpdateTask
ANNOUNCED_STEPS = 7
PAUSE_COUNT = 2


def _cmd_result(stdout: str = "", success: bool = True) -> CommandResult:
    return CommandResult(
        command="",
        returncode=0 if success else 1,
        stdout=stdout,
        stderr="",
        success=success,
    )


def _state_json(archcare_home: Path) -> dict:
    path = archcare_home / ".local/state/archcare/state.json"
    return json.loads(path.read_text()) if path.exists() else {}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_subprocess_checks(mocker):
    """Stub the OS-boundary commands so the task runs fully in memory."""
    mocker.patch(f"{_PACMAN_MODULE}.check_command_exists", return_value=True)
    mocker.patch(f"{_SYSTEM_MODULE}.run_command", return_value=_cmd_result(""))
    mocker.patch(f"{_PACMAN_MODULE}.run_command", return_value=_cmd_result(""))
    mocker.patch(f"{_PACMAN_MODULE}.run_command_with_sudo", return_value=_cmd_result(""))
    mocker.patch(f"{_MODULE}.check_command_exists", return_value=True)
    mocker.patch(f"{_MODULE}.has_interactive_terminal", return_value=True)
    mocker.patch(f"{_MODULE}.has_unread_arch_news", return_value=False)
    mocker.patch(
        f"{_MODULE}.get_pending_repo_updates",
        return_value=[
            PackageUpdateInfo(name=f"pkg{i}", old_version="1.0", new_version="2.0")
            for i in range(30)
        ],
    )
    mocker.patch(f"{_MODULE}.get_pending_aur_updates", return_value=[])
    mocker.patch(f"{_MODULE}.run_system_upgrade", return_value=_cmd_result(""))
    mocker.patch(f"{_MODULE}.run_aur_upgrade", return_value=_cmd_result(""))
    mocker.patch(f"{_MODULE}.detect_btrfs_snapshot_tooling", return_value=False)
    mocker.patch(f"{_MODULE}.get_latest_snapshot_id", return_value=None)


@pytest.fixture(autouse=True)
def mock_task_internal_os_calls(mocker, tmp_path: Path):
    """Stub internal helpers that touch the real filesystem."""
    mocker.patch(
        f"{_MODULE}.snapshot_package_manifest",
        side_effect=lambda p: (
            p.parent.mkdir(parents=True, exist_ok=True),
            p.write_text("linux 6.0\n", encoding="utf-8"),
            p,
        )[2],
    )
    mocker.patch(f"{_MODULE}.backup_sync_db", return_value=tmp_path / "mock_sync_db_backup")
    mocker.patch(f"{_MODULE}.restore_sync_db", return_value=None)
    mocker.patch(f"{_MODULE}.clean_cache", return_value=0)
    mocker.patch(f"{_MODULE}.diff_manifests", return_value=["linux-lts"])
    mocker.patch(f"{_MODULE}.list_pacnew_files", return_value=["/etc/pacman.conf.pacnew"])


# ---------------------------------------------------------------------------
# Happy path: run --force
# ---------------------------------------------------------------------------


class TestSystemUpdateRun:
    def test_run_force_succeeds(self, archcare_home: Path):
        """`run --force` completes with exit 0 and writes success to state.json."""
        runner.invoke(app, ["setup", "config"])

        result = runner.invoke(app, ["task", "run", "system-update", "--force", "--verbose"])

        assert result.exit_code == 0
        assert "success" in result.output.lower() or "Upgraded" in result.output

        state = _state_json(archcare_home)
        assert "system-update" in state.get("tasks", {})
        assert state.get("tasks", {}).get("system-update", {}).get("last_status") == "success"

    def test_run_force_updates_next_due(self, archcare_home: Path):
        """State persistence records `next_due` calculated from frequency (7 days)."""
        runner.invoke(app, ["setup", "config"])
        runner.invoke(app, ["task", "run", "system-update", "--force"])

        state = _state_json(archcare_home)
        task_state = state.get("tasks", {}).get("system-update", {})
        assert "system-update" in state.get("tasks", {})
        assert "next_due" in task_state
        assert task_state["next_due"] is not None


# ---------------------------------------------------------------------------
# Skip path: default threshold gate
# ---------------------------------------------------------------------------


class TestSystemUpdateSkip:
    def test_run_skip_below_threshold(self, mocker, archcare_home: Path):
        """Without `--force`, a pending count below 30 yields NO_WORK_NEEDED skip."""
        mocker.patch(
            f"{_MODULE}.get_pending_repo_updates",
            return_value=[PackageUpdateInfo(name="pkg", old_version="1.0", new_version="2.0")],
        )

        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "system-update"])

        assert result.exit_code == 0
        assert "only 1 repository" in result.output.lower() or "below" in result.output.lower()
        assert "skipped" in result.output.lower()

        state = _state_json(archcare_home)
        # Skipped runs are still recorded with skip reason
        assert "system-update" in state.get("tasks", {})


# ---------------------------------------------------------------------------
# Recover: real record
# ---------------------------------------------------------------------------


class TestSystemUpdateRecover:
    def test_recover_with_real_record(self, archcare_home: Path):
        """`task recover system-update` reads the record and prints executable commands."""
        # Create a recovery record as a real run would write it.
        recovery_dir = archcare_home / ".local/state/archcare/recovery"
        recovery_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "task": "system-update",
            "updated_at": "2026-09-29T18:00:00",
            "sync_db_backup": str(recovery_dir / "sync-db/backup"),
            "manifest_before": str(recovery_dir / "manifests/before.txt"),
            "manifest_after": str(recovery_dir / "manifests/after.txt"),
            "pre_update_snapshot_id": 42,
            "packages_upgraded": ["linux"],
            "packages_removed": ["linux-lts"],
            "aur_packages_failed": ["yay"],
        }
        (recovery_dir / "system-update.json").write_text(json.dumps(record), encoding="utf-8")
        # Ensure the sync-db backup directory exists (the script checks it)
        (recovery_dir / "sync-db/backup").mkdir(parents=True, exist_ok=True)

        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "recover", "system-update"])

        assert result.exit_code == 0
        # Rich applies automatic number styling (`[1;36m` = bold cyan); strip ANSI
        # before substring assertions so the assertion is independent of console state.
        import re

        clean_output = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        assert "snapper rollback 42" in clean_output
        assert "bash" in clean_output
        assert "downgrade.sh" in result.output

    @pytest.mark.usefixtures("archcare_home")
    def test_recover_no_record(self):
        """Without a recovery record, `recover` exits 1 with `No recovery`."""
        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "recover", "system-update"])

        assert result.exit_code == 1
        assert "no recovery" in result.output.lower() or "not found" in result.output.lower()

    def test_recover_script_durable(self, archcare_home: Path):
        """The `downgrade.sh` script is not regenerated if it exists (durable, user-editable)."""
        recovery_dir = archcare_home / ".local/state/archcare/recovery"
        recovery_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "task": "system-update",
            "updated_at": "2026-09-29T18:00:00",
            "sync_db_backup": str(recovery_dir / "sync-db/backup"),
            "pre_update_snapshot_id": 42,
        }
        (recovery_dir / "system-update.json").write_text(json.dumps(record), encoding="utf-8")

        # First recover writes the script.
        runner.invoke(app, ["setup", "config"])
        result_first = runner.invoke(app, ["task", "recover", "system-update"])
        assert result_first.exit_code == 0

        script_path = recovery_dir / "downgrade.sh"
        assert script_path.exists()
        original_content = script_path.read_text(encoding="utf-8")

        # Second recover must leave the script intact (not regenerated).
        result_second = runner.invoke(app, ["task", "recover", "system-update"])
        assert result_second.exit_code == 0
        assert script_path.read_text(encoding="utf-8") == original_content


# ---------------------------------------------------------------------------
# Progress lifecycle (matching health-check reference)
# ---------------------------------------------------------------------------


class TestSystemUpdateProgressReporting:
    def test_progress_start_with_total(self, mock_progress):
        """Real progress adapter reaches `TaskProgress.start()` with total=9."""
        runner.invoke(app, ["setup", "config"])
        runner.invoke(app, ["task", "run", "system-update", "--force"])

        mock_progress.return_value.start.assert_called_once_with(total=STEP_COUNT)

    def test_progress_advanced_per_step(self, mock_progress):
        """The 7 announced steps fire `advance()` exactly 7 times."""
        runner.invoke(app, ["setup", "config"])
        runner.invoke(app, ["task", "run", "system-update", "--force"])

        assert mock_progress.return_value.advance.call_count == ANNOUNCED_STEPS

    def test_progress_stopped_after_run(self, mock_progress):
        """`stop()` fires exactly once after the run completes."""
        runner.invoke(app, ["setup", "config"])
        runner.invoke(app, ["task", "run", "system-update", "--force"])

        mock_progress.return_value.stop.assert_called_once()

    def test_progress_paused_around_transactions(self, mock_progress):
        """Progress is paused three times: around backup_sync_db, pacman, and paru."""
        runner.invoke(app, ["setup", "config"])
        runner.invoke(app, ["task", "run", "system-update", "--force"])

        # Three pauses: one for `backup_sync_db`, one for `pacman -Syu`, one for `paru -Sua`.
        PAUSE_COUNT = 3
        assert mock_progress.return_value.pause.call_count == PAUSE_COUNT

    @pytest.mark.usefixtures("archcare_home")
    def test_progress_lifecycle_on_skip(self, mocker, mock_progress):
        """Even when skipped, the start/advance/stop lifecycle holds for steps reached."""
        mocker.patch(
            f"{_MODULE}.get_pending_repo_updates",
            return_value=[PackageUpdateInfo(name="pkg", old_version="1.0", new_version="2.0")],
        )
        runner.invoke(app, ["setup", "config"])
        runner.invoke(app, ["task", "run", "system-update"])

        # Skip path doesn't reach progress.start() because pre_check / should_run
        # abort before execute(). Verify no start was called in this case.
        mock_progress.return_value.start.assert_not_called()
