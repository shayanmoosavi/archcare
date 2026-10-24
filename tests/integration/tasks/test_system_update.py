"""
Integration tests for system-update task (`task run` and `task recover`).

Real CLI invocation, real AppContext/config I/O, real task
orchestration — only the actual subprocess / OS boundary is mocked.

What this suite covers that the unit suite cannot:

- the *wiring* of every `should_run()` gate to the real CLI: the message the user
  reads, the exit code, and the `skip_reason` that lands in `state.json`,
- the artifacts a real run leaves on disk, and `task recover` reading them back,
- the desktop notification the task sends on each terminal outcome.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from archcare.cli.app import app
from archcare.utils.info_models import MirrorlistInfo, PackageUpdateInfo
from archcare.utils.system import CommandResult
from tests.integration.conftest import clean_output, task_state

type State = dict[str, dict[str, dict[str, Any]]]

runner = CliRunner()

_MODULE = "archcare.tasks.system_update"
_SYSTEM_MODULE = "archcare.utils.system"
_PACMAN_MODULE = "archcare.utils.pacman"

# System-update has 7 announced progress steps (ANNOUNCED_STEPS in unit tests)
STEP_COUNT = 9  # _STEP_COUNT in SystemUpdateTask
ANNOUNCED_STEPS = 7
SNAPSHOT_ID = 42

# The default `min_repo_updates_threshold`. The autouse fixture reports exactly this
# many pending repository updates, so a run clears the threshold gate by default.
REPO_UPDATE_COUNT = 30


def _cmd_result(stdout: str = "", success: bool = True) -> CommandResult:
    return CommandResult(
        command="",
        returncode=0 if success else 1,
        stdout=stdout,
        stderr="",
        success=success,
    )


def _state_json(archcare_home: Path) -> State:
    path = archcare_home / ".local/state/archcare/state.json"
    return json.loads(path.read_text()) if path.exists() else {}


def _stale_mirrorlist(days: int = 10) -> MirrorlistInfo:
    """
    Build a `MirrorlistInfo` whose `last_modified` is `days` in the past.

    The task parses `last_modified` with `datetime.strptime(..., "%Y-%m-%d %H:%M:%S")`,
    so the timestamp must carry that exact format.

    Args:
        days (int): How many days ago the mirrorlist was last modified.

    Returns:
        MirrorlistInfo: A mirrorlist info whose age exceeds the staleness threshold.
    """
    modified = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    return MirrorlistInfo(total_mirrors=5, protocols={"https"}, last_modified=modified)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@dataclass
class _SubprocessMocks:
    """The OS-boundary stubs the task reaches, exposed for call assertions."""

    check_command_exists: MagicMock
    has_interactive_terminal: MagicMock
    has_unread_arch_news: MagicMock
    fetch_arch_news_headlines: MagicMock
    get_mirrorlist_info: MagicMock
    get_pending_kernel_reboot: MagicMock
    get_pending_repo_updates: MagicMock
    get_pending_aur_updates: MagicMock
    run_system_upgrade: MagicMock
    run_aur_upgrade: MagicMock
    detect_btrfs_snapshot_tooling: MagicMock
    get_latest_snapshot_id: MagicMock


@dataclass
class _TaskInternalMocks:
    """The helpers that touch the real filesystem, exposed for call assertions."""

    snapshot_package_manifest: MagicMock
    backup_sync_db: MagicMock
    restore_sync_db: MagicMock
    clean_cache: MagicMock
    diff_manifests: MagicMock
    list_pacnew_files: MagicMock


@pytest.fixture(autouse=True)
def mock_subprocess_checks(mocker) -> _SubprocessMocks:
    """
    Stub the OS-boundary commands so the task runs fully in memory.

    Every name the task imports from `archcare.utils` is patched *in the task
    module*, which is where the task actually looks it up. `fetch_arch_news_headlines`
    is included because the real one shells out to `informant`/`paru` — leaving it
    real would put a real subprocess on the developer's machine the moment a test
    makes unread news visible.

    Returns:
        _SubprocessMocks: The installed stubs, for call assertions.
    """
    mocker.patch(f"{_PACMAN_MODULE}.check_command_exists", return_value=True)
    mocker.patch(f"{_SYSTEM_MODULE}.run_command", return_value=_cmd_result(""))
    mocker.patch(f"{_PACMAN_MODULE}.run_command", return_value=_cmd_result(""))
    mocker.patch(f"{_PACMAN_MODULE}.run_command_with_sudo", return_value=_cmd_result(""))

    stubs: dict[str, dict[str, Any]] = {
        "check_command_exists": {"return_value": True},
        "has_interactive_terminal": {"return_value": True},
        "has_unread_arch_news": {"return_value": False},
        "fetch_arch_news_headlines": {"return_value": []},
        "get_mirrorlist_info": {"return_value": MirrorlistInfo(5, {"https"})},
        "get_pending_kernel_reboot": {"return_value": None},
        "get_pending_repo_updates": {
            "return_value": [
                PackageUpdateInfo(name=f"pkg{i}", old_version="1.0", new_version="2.0")
                for i in range(REPO_UPDATE_COUNT)
            ]
        },
        "get_pending_aur_updates": {"return_value": []},
        "run_system_upgrade": {"return_value": _cmd_result("")},
        "run_aur_upgrade": {"return_value": _cmd_result("")},
        "detect_btrfs_snapshot_tooling": {"return_value": False},
        "get_latest_snapshot_id": {"return_value": None},
    }
    mocks: dict[str, MagicMock] = {
        name: mocker.patch(f"{_MODULE}.{name}", **kwargs) for name, kwargs in stubs.items()
    }
    return _SubprocessMocks(**mocks)


@pytest.fixture(autouse=True)
def mock_task_internal_os_calls(mocker, tmp_path: Path) -> _TaskInternalMocks:
    """
    Stub internal helpers that touch the real filesystem.

    Returns:
        _TaskInternalMocks: The installed stubs, for call assertions.
    """
    manifest: MagicMock = mocker.patch(
        f"{_MODULE}.snapshot_package_manifest",
        # Every line in the lambda expression is evaluated and the last one is returned
        side_effect=lambda p: (
            p.parent.mkdir(parents=True, exist_ok=True),
            p.write_text("linux 6.0\n", encoding="utf-8"),
            p,
        )[2],
    )
    backup: MagicMock = mocker.patch(
        f"{_MODULE}.backup_sync_db", return_value=tmp_path / "mock_sync_db_backup"
    )
    restore: MagicMock = mocker.patch(f"{_MODULE}.restore_sync_db", return_value=None)
    cache: MagicMock = mocker.patch(f"{_MODULE}.clean_cache", return_value=0)
    diff: MagicMock = mocker.patch(f"{_MODULE}.diff_manifests", return_value=["linux-lts"])
    pacnew: MagicMock = mocker.patch(
        f"{_MODULE}.list_pacnew_files", return_value=["/etc/pacman.conf.pacnew"]
    )
    return _TaskInternalMocks(
        snapshot_package_manifest=manifest,
        backup_sync_db=backup,
        restore_sync_db=restore,
        clean_cache=cache,
        diff_manifests=diff,
        list_pacnew_files=pacnew,
    )


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
        tasks = state.get("tasks", {})
        assert "system-update" in tasks
        assert tasks["system-update"].get("last_status") == "success"

    def test_run_force_updates_next_due(self, archcare_home: Path):
        """State persistence records `next_due` calculated from frequency (7 days)."""
        runner.invoke(app, ["setup", "config"])
        runner.invoke(app, ["task", "run", "system-update", "--force"])

        state = _state_json(archcare_home)
        tasks = state.get("tasks", {})
        assert "system-update" in tasks
        system_update = tasks["system-update"]
        assert "next_due" in system_update
        assert system_update["next_due"] is not None

    def test_run_writes_a_recovery_record(self, archcare_home: Path):
        """
        A successful run leaves the record `task recover` reads.

        The record is the only durable trace of what the transaction did — the
        transaction's own output was never captured — so its presence and content
        are the contract between the task and the recovery command.
        """
        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "system-update", "--force"])

        assert result.exit_code == 0
        record_path = archcare_home / ".local/state/archcare/recovery/system-update.json"
        assert record_path.exists()

        record = json.loads(record_path.read_text())
        assert record["task"] == "system-update"
        assert record["packages_upgraded"] == [f"pkg{i}" for i in range(REPO_UPDATE_COUNT)]
        assert record["packages_removed"] == ["linux-lts"]
        assert record["aur_packages_failed"] == []

    def test_verbose_renders_the_task_details(self):
        """`--verbose` reaches the task's formatter through the registry."""
        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "system-update", "--force", "--verbose"])

        assert result.exit_code == 0
        output = clean_output(result.output)
        assert f"Packages: {REPO_UPDATE_COUNT} repository" in output
        assert "Packages removed" in output
        assert "linux-lts" in output
        assert ".pacnew files" in output
        assert "Cache cleaned" in output


# ---------------------------------------------------------------------------
# Pre-check: missing prerequisites
# ---------------------------------------------------------------------------


class TestSystemUpdatePreCheck:
    """
    `pre_check()` failures skip the task before it touches anything.

    These are the only skips that mean "the environment is broken" rather than
    "there is nothing to do", so they are classified as `dependency_failed`.
    """

    def test_missing_pacman_skips_with_the_arch_wiki_guide(
        self, archcare_home: Path, mock_subprocess_checks: _SubprocessMocks
    ):
        mock_subprocess_checks.check_command_exists.side_effect = lambda cmd: cmd != "pacman"

        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "system-update", "--force"])

        assert result.exit_code == 0
        assert "SKIPPED" in result.output
        assert "Arch wiki" in clean_output(result.output)
        assert task_state(archcare_home, "system-update")["skip_reason"] == "dependency_failed"
        assert mock_subprocess_checks.run_system_upgrade.call_count == 0

    def test_missing_paru_skips_with_an_aur_install_hint(
        self, archcare_home: Path, mock_subprocess_checks: _SubprocessMocks
    ):
        """
        `paru` is an AUR package, so the hint must not tell the user to install it
        with pacman — pacman cannot build AUR packages.
        """
        mock_subprocess_checks.check_command_exists.side_effect = lambda cmd: cmd != "paru"

        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "system-update", "--force"])

        assert result.exit_code == 0
        output = clean_output(result.output)
        assert "paru" in output
        assert "makepkg" in output
        assert "aur.archlinux.org/paru" in output
        assert "sudo pacman -S paru" not in output
        assert task_state(archcare_home, "system-update")["skip_reason"] == "dependency_failed"
        assert mock_subprocess_checks.run_system_upgrade.call_count == 0

    def test_missing_checkupdates_skips_with_a_pacman_contrib_hint(
        self, archcare_home: Path, mock_subprocess_checks: _SubprocessMocks
    ):
        """`checkupdates` ships in `pacman-contrib` — the hint must name that package."""
        mock_subprocess_checks.check_command_exists.side_effect = lambda cmd: cmd != "checkupdates"

        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "system-update", "--force"])

        assert result.exit_code == 0
        assert "sudo pacman -S pacman-contrib" in clean_output(result.output)
        assert task_state(archcare_home, "system-update")["skip_reason"] == "dependency_failed"
        assert mock_subprocess_checks.run_system_upgrade.call_count == 0

    def test_missing_terminal_skips_with_an_interactive_terminal_message(
        self, archcare_home: Path, mock_subprocess_checks: _SubprocessMocks
    ):
        """
        Both transaction halves inherit stdio, so without a TTY there is nowhere for
        pacman's confirmation to render.
        """
        mock_subprocess_checks.has_interactive_terminal.return_value = False

        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "system-update", "--force"])

        assert result.exit_code == 0
        assert "interactive terminal" in clean_output(result.output)
        assert task_state(archcare_home, "system-update")["skip_reason"] == "dependency_failed"
        assert mock_subprocess_checks.run_system_upgrade.call_count == 0


# ---------------------------------------------------------------------------
# Skip path: `should_run` gates
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
        tasks = state.get("tasks", {})
        assert "system-update" in tasks
        system_update = tasks["system-update"]
        assert system_update.get("skip_reason") == "no_work_needed"
        assert system_update["next_due"] is not None

    def test_run_skips_when_the_mirrorlist_is_stale(
        self, archcare_home: Path, mock_subprocess_checks: _SubprocessMocks
    ):
        """
        A stale mirrorlist is reported before any update query is spent.

        The mirrorlist is the cheaper fix, so it wins over every later gate, and the network query
        that would follow it must not run at all.
        """
        mock_subprocess_checks.get_mirrorlist_info.return_value = _stale_mirrorlist()

        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "system-update", "--force"])

        assert result.exit_code == 0
        output = clean_output(result.output)
        assert "SKIPPED" in output
        assert "older than 7 days" in output
        assert "archcare task run mirrorlist-update" in output
        assert task_state(archcare_home, "system-update")["skip_reason"] == "mirrorlist_stale"
        assert mock_subprocess_checks.get_pending_repo_updates.call_count == 0
        assert mock_subprocess_checks.run_system_upgrade.call_count == 0

    def test_run_skips_when_a_reboot_is_pending(
        self, archcare_home: Path, mock_subprocess_checks: _SubprocessMocks
    ):
        """
        A replaced running kernel blocks the transaction.

        The message names both the running kernel and the one that replaced it, so the user can tell
        which package to expect after rebooting.
        """
        mock_subprocess_checks.get_pending_kernel_reboot.return_value = (
            "6.12.1-arch1-1",
            ["6.12.2.arch1-1"],
        )

        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "system-update", "--force"])

        assert result.exit_code == 0
        output = clean_output(result.output)
        assert "SKIPPED" in output
        assert "Pending reboot" in output
        assert "(6.12.1-arch1-1) was replaced" in output
        assert "6.12.2.arch1-1" in output
        assert task_state(archcare_home, "system-update")["skip_reason"] == "reboot_required"
        assert mock_subprocess_checks.run_system_upgrade.call_count == 0

    def test_run_skips_when_the_user_declines_unread_news(
        self, archcare_home: Path, mock_subprocess_checks: _SubprocessMocks
    ):
        """
        Declining the news acknowledgement skips the update.

        The prompt is rendered by the real CLI interaction port, so this asserts that the question
        actually reaches the user's terminal.
        """
        mock_subprocess_checks.has_unread_arch_news.return_value = True
        mock_subprocess_checks.fetch_arch_news_headlines.return_value = [
            "glibc 2.41 requires manual intervention"
        ]

        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "system-update", "--force"], input="n\n")

        assert result.exit_code == 0
        output = clean_output(result.output)
        assert "Proceed with the system update anyway?" in output
        assert "SKIPPED" in output
        assert "declined" in output.lower()
        assert task_state(archcare_home, "system-update")["skip_reason"] == "user_cancelled"
        assert mock_subprocess_checks.run_system_upgrade.call_count == 0

    def test_run_proceeds_when_the_user_acknowledges_unread_news(
        self, archcare_home: Path, mock_subprocess_checks: _SubprocessMocks
    ):
        """Accepting the news acknowledgement lets the transaction run."""
        mock_subprocess_checks.has_unread_arch_news.return_value = True
        mock_subprocess_checks.fetch_arch_news_headlines.return_value = [
            "glibc 2.41 requires manual intervention"
        ]

        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "system-update", "--force"], input="y\n")

        assert result.exit_code == 0
        assert "Proceed with the system update anyway?" in clean_output(result.output)
        assert mock_subprocess_checks.run_system_upgrade.call_count == 1
        assert task_state(archcare_home, "system-update")["last_status"] == "success"

    def test_the_news_prompt_is_not_repeated_within_the_cooldown(
        self, archcare_home: Path, mock_subprocess_checks: _SubprocessMocks
    ):
        """
        A second run inside the cooldown window must not ask again.

        The cooldown lives in `state.json`, so this only holds if the prompt timestamp really
        survives the run and is read back by the next one.
        """
        mock_subprocess_checks.has_unread_arch_news.return_value = True

        runner.invoke(app, ["setup", "config"])
        first = runner.invoke(app, ["task", "run", "system-update", "--force"], input="n\n")
        assert first.exit_code == 0
        assert "Proceed with the system update anyway?" in clean_output(first.output)
        assert task_state(archcare_home, "system-update")["last_news_prompt"] is not None

        second = runner.invoke(app, ["task", "run", "system-update", "--force"])

        assert second.exit_code == 0
        assert "Proceed with the system update anyway?" not in clean_output(second.output)
        assert mock_subprocess_checks.run_system_upgrade.call_count == 1

    def test_a_blocked_run_preserves_the_next_due(
        self, archcare_home: Path, mock_subprocess_checks: _SubprocessMocks
    ):
        """
        A blocked run must not slide the schedule forward.

        A stale mirrorlist means the update never happened, so the next attempt stays where it was
        — the task is still due and is retried. Only a run that actually *checked* the system counts
        as a completed cycle.
        """
        runner.invoke(app, ["setup", "config"])
        runner.invoke(app, ["task", "run", "system-update", "--force"])
        next_due_after_success = task_state(archcare_home, "system-update")["next_due"]
        assert next_due_after_success is not None

        mock_subprocess_checks.get_mirrorlist_info.return_value = _stale_mirrorlist()
        blocked = runner.invoke(app, ["task", "run", "system-update", "--force"])

        assert blocked.exit_code == 0
        assert task_state(archcare_home, "system-update")["skip_reason"] == "mirrorlist_stale"
        assert task_state(archcare_home, "system-update")["next_due"] == next_due_after_success

    def test_a_blocked_run_on_a_fresh_state_schedules_nothing(
        self, archcare_home: Path, mock_subprocess_checks: _SubprocessMocks
    ):
        """
        A blocked run with no prior schedule leaves no schedule behind.

        This is the same rule as the preserved-date case above, seen from the other side: the
        executor only *keeps* a `next_due` that already existed, it never invents one for a run
        that was blocked.
        """
        mock_subprocess_checks.get_mirrorlist_info.return_value = _stale_mirrorlist()

        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "system-update", "--force"])

        assert result.exit_code == 0
        assert task_state(archcare_home, "system-update")["skip_reason"] == "mirrorlist_stale"
        assert task_state(archcare_home, "system-update")["next_due"] is None


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


class TestSystemUpdateFailures:
    def test_a_pacman_failure_fails_the_run_and_restores_the_sync_database(
        self, archcare_home: Path, mock_subprocess_checks: _SubprocessMocks
    ):
        """
        A failed `pacman -Syu` is fatal, and the sync database is rolled back.

        The database was already refreshed by the aborted transaction, so leaving
        it in place would describe a repository state the system never reached.
        """
        mock_subprocess_checks.run_system_upgrade.return_value = _cmd_result("", success=False)

        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "system-update", "--force"])

        assert result.exit_code == 1
        assert "pacman -Syu" in clean_output(result.output)
        state = task_state(archcare_home, "system-update")
        assert state["last_status"] == "failure"
        assert "pacman -Syu" in state["last_error"]

    def test_a_pacman_failure_restores_the_backup_it_took(
        self,
        mock_subprocess_checks: _SubprocessMocks,
        mock_task_internal_os_calls: _TaskInternalMocks,
    ):
        """
        The rollback restores the backup that `execute()` took.

        Asserting on the argument rather than the call count pins *which* backup is
        used: a rollback against a stale or freshly-named path would restore the
        wrong state while a count-based assertion still passed.
        """
        mock_subprocess_checks.run_system_upgrade.return_value = _cmd_result("", success=False)

        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "system-update", "--force"])

        assert result.exit_code == 1
        mock_task_internal_os_calls.restore_sync_db.assert_called_once_with(
            mock_task_internal_os_calls.backup_sync_db.return_value
        )

    def test_a_pacman_failure_writes_no_recovery_record(
        self, archcare_home: Path, mock_subprocess_checks: _SubprocessMocks
    ):
        """
        An aborted transaction leaves no recovery record.

        The record describes what a *completed* upgrade changed; for an aborted one
        it would name artifacts that describe the wrong system state.
        """
        mock_subprocess_checks.run_system_upgrade.return_value = _cmd_result("", success=False)

        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "system-update", "--force"])

        assert result.exit_code == 1
        assert not (archcare_home / ".local/state/archcare/recovery/system-update.json").exists()

    def test_a_failed_backup_stops_before_the_transaction(
        self,
        archcare_home: Path,
        mock_subprocess_checks: _SubprocessMocks,
        mock_task_internal_os_calls: _TaskInternalMocks,
    ):
        """
        No safety net, no transaction.

        A failure to back up the sync database must abort before anything is upgraded — and there is
        nothing to roll back, because nothing changed.
        """
        mock_task_internal_os_calls.backup_sync_db.side_effect = OSError("disk full")

        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "system-update", "--force"])

        assert result.exit_code == 1
        assert "Failed to back up the pacman sync database" in clean_output(result.output)
        assert mock_subprocess_checks.run_system_upgrade.call_count == 0
        assert mock_task_internal_os_calls.restore_sync_db.call_count == 0
        state = task_state(archcare_home, "system-update")
        assert state["last_status"] == "failure"
        assert state["last_error"] == "disk full"

    def test_an_aur_failure_reports_a_partial_result(
        self,
        archcare_home: Path,
        mock_subprocess_checks: _SubprocessMocks,
        mock_task_internal_os_calls: _TaskInternalMocks,
    ):
        """
        A failed AUR half is partial, not fatal.

        The repository half already landed, so the sync database is consistent and must not be
        rolled back; the packages that failed to build are reported so the user can rebuild them.
        """
        mock_subprocess_checks.run_aur_upgrade.return_value = _cmd_result("", success=False)
        mock_subprocess_checks.get_pending_aur_updates.return_value = [
            PackageUpdateInfo(name="yay", old_version="1.0", new_version="2.0")
        ]

        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "system-update", "--force"])

        assert result.exit_code == 0
        assert "PARTIAL" in result.output
        assert task_state(archcare_home, "system-update")["last_status"] == "partial"
        # The cache holds the artifacts a manual downgrade needs — a partial run must not prune it.
        assert mock_task_internal_os_calls.clean_cache.call_count == 0

    def test_an_aur_failure_still_writes_the_recovery_record(
        self, archcare_home: Path, mock_subprocess_checks: _SubprocessMocks
    ):
        """A partial run is exactly when a user goes looking for the record."""
        mock_subprocess_checks.run_aur_upgrade.return_value = _cmd_result("", success=False)
        mock_subprocess_checks.get_pending_aur_updates.return_value = [
            PackageUpdateInfo(name="yay", old_version="1.0", new_version="2.0")
        ]

        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "system-update", "--force"])

        assert result.exit_code == 0
        record_path = archcare_home / ".local/state/archcare/recovery/system-update.json"
        record = json.loads(record_path.read_text())
        assert record["aur_packages_failed"] == ["yay"]
        assert record["packages_upgraded"] == [f"pkg{i}" for i in range(REPO_UPDATE_COUNT)]


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


class TestSystemUpdateNotifications:
    def test_a_successful_run_is_announced(self, mock_notification_manager):
        """
        A successful upgrade is worth a desktop notification.

        The task is MANUAL and takes many minutes, so the user may well have walked away by the time
        it ends.
        """
        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "system-update", "--force"])

        assert result.exit_code == 0
        mock_notification_manager.return_value.send_task_result_notification.assert_called_once_with(
            task_name="system-update",
            success=True,
            message=f"Upgraded {REPO_UPDATE_COUNT} repository and 0 AUR package(s)",
        )

    @pytest.mark.usefixtures("mock_subprocess_checks")
    def test_a_failed_run_is_announced(
        self, mock_notification_manager, mock_task_internal_os_calls: _TaskInternalMocks
    ):
        """
        A failure is the case that matters most — the user needs to know it happened.

        The backup failure is a *graceful* failure: `execute()` returns a failed result, so
        `post_execute()` runs and announces it.
        """
        mock_task_internal_os_calls.backup_sync_db.side_effect = OSError("disk full")

        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "system-update", "--force"])

        assert result.exit_code == 1
        mock_notification_manager.return_value.send_task_result_notification.assert_called_once_with(
            task_name="system-update",
            success=False,
            message="Failed to back up the pacman sync database: disk full",
        )

    def test_a_partial_run_is_announced_as_a_failure(
        self, mock_notification_manager, mock_subprocess_checks: _SubprocessMocks
    ):
        """
        A partial run is announced as a failure.

        The AUR half failed, so the upgrade did not fully land; a green tick would be the wrong
        summary of what happened.
        """
        mock_subprocess_checks.run_aur_upgrade.return_value = _cmd_result("", success=False)
        mock_subprocess_checks.get_pending_aur_updates.return_value = [
            PackageUpdateInfo(name="yay", old_version="1.0", new_version="2.0")
        ]

        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "system-update", "--force"])

        assert result.exit_code == 0
        mock_notification_manager.return_value.send_task_result_notification.assert_called_once_with(
            task_name="system-update",
            success=False,
            message=f"Upgraded {REPO_UPDATE_COUNT} repository package(s), but 1 AUR package(s) "
            "failed to build or install",
        )


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

    def test_recover_reads_the_record_a_real_run_wrote(self, archcare_home: Path):
        """
        The round trip: a run writes the record, `recover` reads that same file.

        A record written by hand could agree with the reader while disagreeing with the writer; only
        a real run proves the two halves fit.
        """
        runner.invoke(app, ["setup", "config"])
        run = runner.invoke(app, ["task", "run", "system-update", "--force"])
        assert run.exit_code == 0

        result = runner.invoke(app, ["task", "recover", "system-update"])

        assert result.exit_code == 0
        output = clean_output(result.output)
        assert "Recovery Info" in output
        assert "Packages removed: linux-lts" in output
        assert (archcare_home / ".local/state/archcare/recovery/downgrade.sh").exists()

    def test_recover_reports_a_corrupt_record(self, archcare_home: Path):
        """A record that cannot be parsed is reported, not silently treated as absent."""
        recovery_dir = archcare_home / ".local/state/archcare/recovery"
        recovery_dir.mkdir(parents=True, exist_ok=True)
        (recovery_dir / "system-update.json").write_text("{not json", encoding="utf-8")

        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "recover", "system-update"])

        assert result.exit_code == 1
        assert "unreadable" in result.output.lower()

    def test_recover_for_a_task_without_recovery_support(self):
        """A task that leaves no recovery record has nothing to recover."""
        runner.invoke(app, ["setup", "config"])

        result = runner.invoke(app, ["task", "recover", "health-check"])

        assert result.exit_code == 1
        assert "no recovery record" in result.output.lower()


# ---------------------------------------------------------------------------
# Progress lifecycle
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
        """
        Every sudo-touching call and command that needs interactive input (e.g., `paru`'s
        interactive PKGBUILD review or `pacman` transaction prompts) in the run pauses the display
        around its password prompt.
        """
        runner.invoke(app, ["setup", "config"])
        runner.invoke(app, ["task", "run", "system-update", "--force"])

        # Four pauses: one for `backup_sync_db`, one for `pacman -Syu`, one for `paru -Sua`,
        # and one for `paccache` in post_execute. The snapper lookup pauses too, but snapshot
        # tooling is stubbed off by the autouse fixtures, so that branch does not run here
        # (covered by `test_progress_paused_with_btrfs_snapshot` below).
        PAUSE_COUNT = 4
        assert mock_progress.return_value.pause.call_count == PAUSE_COUNT

    def test_progress_paused_with_btrfs_snapshot(self, mocker, mock_progress, archcare_home: Path):
        """
        With snapper tooling present, the sudo `snapper list` lookup is also paused.

        `run_command_with_sudo` presumes root, and a swallowed interactive prompt would leave the
        terminal unusable mid-transaction — the same reasoning as backup/pacman/paru. Tooling
        is forced on so the snapper branch actually runs; the lookup helper itself is stubbed
        to a fixed id so the recovery record is deterministic.
        """
        mocker.patch(f"{_MODULE}.detect_btrfs_snapshot_tooling", return_value=True)
        mocker.patch(f"{_MODULE}.get_latest_snapshot_id", return_value=SNAPSHOT_ID)

        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "system-update", "--force"])

        assert result.exit_code == 0
        # Five pauses: backup_sync_db, pacman, paru, the sudo snapper lookup, and `paccache`.
        PAUSE_COUNT = 5
        assert mock_progress.return_value.pause.call_count == PAUSE_COUNT

        record = json.loads(
            (archcare_home / ".local/state/archcare/recovery/system-update.json").read_text()
        )
        assert record["pre_update_snapshot_id"] == SNAPSHOT_ID

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
