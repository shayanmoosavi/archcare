"""
Integration tests for the mirrorlist-update task.

Uses a 'smart mock' router to intercept root-level file operations and
safely redirect them to shutil within the Pytest tmp_path sandbox.
"""

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from archcare.cli.app import app
from archcare.utils.system import CommandResult

runner = CliRunner()

_SYSTEM_MODULE = "archcare.utils.mirrorlist"
_MODULE = "archcare.tasks.mirrorlist_update"


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _fake_run_with_sudo(command, **_) -> CommandResult:
    """
    Intercepts dangerous sudo commands and safely executes them in memory/tmp.
    """
    command_list = command if isinstance(command, list) else command.split()

    if command_list[0] == "cp":
        # Intercept: ["cp", "-p", src, dst]
        src, dst = command_list[2], command_list[3]
        shutil.copy2(src, dst)
        return CommandResult(
            command=" ".join(command_list),
            returncode=0,
            stdout="",
            stderr="",
            success=True,
        )

    if command_list[0] == "reflector":
        # Intercept reflector and manually write a fake successful mirrorlist
        save_idx = command_list.index("--save") + 1
        save_path = Path(command_list[save_idx])
        save_path.write_text("Server = https://fast.mocked.mirror.com/$repo/os/$arch\n")
        return CommandResult(
            command=" ".join(command_list),
            returncode=0,
            stdout="",
            stderr="",
            success=True,
        )

    return CommandResult(
        command=" ".join(command_list), returncode=0, stdout="", stderr="", success=True
    )


@pytest.fixture
def sandbox(archcare_home: Path, mocker):
    """
    Initializes the app configs, creates a fake mirrorlist in tmp_path,
    and updates settings.toml to point the task at our sandbox.
    """
    # 1. Initialize configs
    runner.invoke(app, ["setup", "config"])

    # 2. Create the sandbox mirrorlist
    sandbox_mirrorlist = archcare_home / "etc/pacman.d/mirrorlist"
    sandbox_mirrorlist.parent.mkdir(parents=True, exist_ok=True)
    original_content = "Server = https://old.slow.mirror.com/$repo/os/$arch\n"
    sandbox_mirrorlist.write_text(original_content)

    # 3. Modify settings.toml to point to our sandbox instead of /etc
    settings_file = archcare_home / ".config/archcare/settings.toml"
    with open(settings_file, "w") as f:
        f.write("\n[mirrorlist]\n")
        f.write(f'path = "{sandbox_mirrorlist}"\n')

    # 4. Patch command dependencies globally for this test class
    mocker.patch(f"{_MODULE}.check_command_exists", return_value=True)
    mocker.patch(f"{_SYSTEM_MODULE}.check_command_exists", return_value=True)
    mocker.patch(f"{_SYSTEM_MODULE}.run_command_with_sudo", side_effect=_fake_run_with_sudo)

    return sandbox_mirrorlist


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


class TestMirrorlistUpdateTask:
    def test_mirrorlist_update_happy_path(self, sandbox: Path):
        """Verify the task backs up, updates, validates, and succeeds."""

        result = runner.invoke(app, ["task", "run", "mirrorlist-update", "--verbose"])

        assert result.exit_code == 0
        print(list(sandbox.parent.glob("mirrorlist.*")))
        assert "Mirrorlist updated successfully" in result.output

        # Verify the file was actually overwritten by our smart mock
        content = sandbox.read_text()
        assert "fast.mocked.mirror.com" in content

        # Verify backup was created
        backups = list(sandbox.parent.glob("mirrorlist_*.backup"))
        assert len(backups) == 1
        assert "old.slow.mirror.com" in backups[0].read_text()

    def test_aborts_if_reflector_missing(self, sandbox: Path, mocker):
        """Verify pre_check safely halts execution before touching files."""
        mocker.patch(f"{_MODULE}.check_command_exists", return_value=False)

        result = runner.invoke(app, ["task", "run", "mirrorlist-update"])

        # Task skips gracefully
        assert result.exit_code == 0
        assert "reflector is not installed" in result.output

        # File should remain untouched, no backups created
        assert len(list(sandbox.parent.glob("*.backup"))) == 0

    def test_backup_creation_failure_aborts_and_fails_cleanly(self, sandbox: Path, mocker):
        """
        Verify task aborts the execution immediately and fails cleanly if
        backup creation fails.
        """

        mocker.patch(f"{_MODULE}.backup_file", side_effect=OSError("Unexpected error"))

        result = runner.invoke(app, ["task", "run", "mirrorlist-update"])

        assert result.exit_code == 1
        assert "Failed to create" in result.output
        assert "Unexpected error" in result.output

        # The file content MUST be the original state
        content = sandbox.read_text()
        assert "old.slow.mirror.com" in content

    def test_rollback_on_reflector_crash(self, sandbox: Path, mocker):
        """Verify original file is restored if reflector times out or crashes."""

        # Override the smart mock just for this test to simulate a crash
        def _fail_reflector(command, **kwargs):
            if command[0] == "reflector":
                return CommandResult(
                    command="reflector",
                    returncode=1,
                    stdout="",
                    stderr="Timeout",
                    success=False,
                )
            return _fake_run_with_sudo(command, **kwargs)  # Fallback to handle cp

        mocker.patch(f"{_SYSTEM_MODULE}.run_command_with_sudo", side_effect=_fail_reflector)

        # Running with --devel to output log messages
        result = runner.invoke(app, ["--devel", "task", "run", "mirrorlist-update"])

        # The task should fail gracefully, catching the exception
        assert result.exit_code == 1
        assert "Rolling back" in result.output  # Only exists in logs

        # The file content MUST be the original state
        content = sandbox.read_text()
        assert "old.slow.mirror.com" in content

    def test_rollback_on_validation_failure(self, sandbox: Path, mocker):
        """Verify original file is restored if reflector writes an empty/invalid file."""

        # Override the smart mock to "succeed" but write garbage data
        def _write_garbage(command, **kwargs):
            if command[0] == "reflector":
                save_idx = command.index("--save") + 1
                Path(command[save_idx]).write_text("<html>502 Bad Gateway</html>\n")
                return CommandResult(
                    command="reflector",
                    returncode=0,
                    stdout="",
                    stderr="",
                    success=True,
                )
            return _fake_run_with_sudo(command, **kwargs)

        mocker.patch(f"{_SYSTEM_MODULE}.run_command_with_sudo", side_effect=_write_garbage)

        result = runner.invoke(app, ["task", "run", "mirrorlist-update"])

        assert result.exit_code == 1
        assert "validation failed" in result.output.lower()

        # The file content MUST be the original state
        content = sandbox.read_text()
        assert "old.slow.mirror.com" in content

    def test_cleans_up_old_backups(self, sandbox: Path):
        """Verify the task correctly purges old backups, keeping only the 5 most recent."""
        import os
        import time

        backup_dir = sandbox.parent

        # Create 6 "old" backups with staggered modification times
        for i in range(1, 7):
            old_backup = backup_dir / f"mirrorlist_2026-01-0{i}_120000.backup"
            old_backup.write_text(f"Old backup {i}")

            # Stagger the mtimes so i=1 is the absolute oldest
            # Subtracting minutes into the past ensures they are older than the new backup
            past_time = time.time() - (100 - i) * 60
            os.utime(old_backup, (past_time, past_time))

        # Sanity check before run:
        # We should have 1 sandbox mirrorlist + 6 backups = 7 files total
        assert len(list(backup_dir.glob("mirrorlist_*.backup"))) == 6

        # It creates 1 new backup (total 7), then post_execute purges
        # the oldest 2 (leaving 5).
        result = runner.invoke(app, ["task", "run", "mirrorlist-update"])

        assert result.exit_code == 0

        # Verify exactly 5 backups remain
        remaining_backups = list(backup_dir.glob("mirrorlist_*.backup"))
        assert len(remaining_backups) == 5

        # Verify the absolute oldest files (i=1 and i=2) were the ones deleted
        remaining_names = [b.name for b in remaining_backups]
        assert not any("2026-01-01" in name for name in remaining_names)
        assert not any("2026-01-02" in name for name in remaining_names)


class TestMirrorlistUpdateProgressReporting:
    """
    mirrorlist-update is the spinner-only task - no start()/advance() calls
    at all, since reflector's duration isn't decomposable into known steps.
    """

    def test_spinner_used_around_reflector_call(self, sandbox: Path, mock_progress):
        result = runner.invoke(app, ["task", "run", "mirrorlist-update", "--verbose"])

        assert result.exit_code == 0
        mock_progress.return_value.spinner.assert_called_once()

    def test_spinner_still_used_when_reflector_fails(self, sandbox: Path, mocker, mock_progress):
        """Spinner must wrap the call itself, not just the success path -
        it needs to close cleanly even when reflector reports failure."""

        def _fail_reflector(command, **kwargs):
            if command[0] == "reflector":
                return CommandResult(
                    command="reflector",
                    returncode=1,
                    stdout="",
                    stderr="Timeout",
                    success=False,
                )
            return _fake_run_with_sudo(command, **kwargs)

        mocker.patch(f"{_SYSTEM_MODULE}.run_command_with_sudo", side_effect=_fail_reflector)

        result = runner.invoke(app, ["task", "run", "mirrorlist-update"])

        assert result.exit_code == 1
        mock_progress.return_value.spinner.assert_called_once()

    def test_spinner_not_used_when_precheck_fails(self, sandbox: Path, mocker, mock_progress):
        """pre_check() rejects before execute() ever runs - the reflector
        call, and therefore the surrounding spinner, should never happen."""
        mocker.patch(f"{_MODULE}.check_command_exists", return_value=False)

        runner.invoke(app, ["task", "run", "mirrorlist-update"])

        mock_progress.return_value.spinner.assert_not_called()

    def test_no_determinate_bar_used(self, sandbox: Path, mock_progress):
        """Regression guard: this task should stay spinner-only. If a
        future edit adds report_progress() calls here, that's a design
        change worth a deliberate decision, not an accidental drift."""
        runner.invoke(app, ["task", "run", "mirrorlist-update"])

        mock_progress.return_value.start.assert_not_called()
        mock_progress.return_value.advance.assert_not_called()

    def test_progress_stopped_after_run(self, sandbox: Path, mock_progress):
        runner.invoke(app, ["task", "run", "mirrorlist-update"])

        mock_progress.return_value.stop.assert_called_once()
