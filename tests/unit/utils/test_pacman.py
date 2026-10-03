"""Unit tests for pacman utility functions."""

from dataclasses import dataclass
from pathlib import Path
from subprocess import CalledProcessError
from unittest.mock import MagicMock

import pytest

from archcare.utils.pacman import (
    backup_sync_db,
    check_package_files,
    check_pacman_database,
    clean_cache,
    diff_manifests,
    get_pending_repo_updates,
    list_pacnew_files,
    parse_pending_updates,
    restore_sync_db,
    run_system_upgrade,
    snapshot_package_manifest,
)
from archcare.utils.system import CommandResult

_MODULE = "archcare.utils.pacman"

_PATCH_CHECK_COMMAND = f"{_MODULE}.check_command_exists"
_PATCH_RUN_COMMAND_SUDO = f"{_MODULE}.run_command_with_sudo"
_PATCH_SYNC_DB = f"{_MODULE}.SYNC_DB_PATH"

# ---------------------------------------------------------------------------
# Fixtures and Helpers
# ---------------------------------------------------------------------------


@dataclass
class MockResult:
    """Helper to simulate the CommandResult dataclass"""

    success: bool = True
    stdout: str = ""
    stderr: str = ""


def _result(
    commanad: str = "test",
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
    success: bool | None = None,
) -> CommandResult:
    """Build a real `CommandResult`, deriving `success` from the exit code.

    When `success` is given explicitly it overrides the default (`returncode == 0`),
    letting callers reproduce the special-cased success logic that `run_command`
    applies for tools such as `systemctl` (exit 3) and `checkupdates` (exit 2).

    The genuine dataclass is used rather than `MockResult` because the update queries
    branch on `returncode` — notably `checkupdates`, which exits 2 to mean "no updates".
    """
    return CommandResult(
        command=commanad,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        success=success if success is not None else returncode == 0,
    )


def _write(path: Path, content: str) -> Path:
    """Write manifest content to `path` and return it."""
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def mock_run_command(mocker) -> MagicMock:
    return mocker.patch(f"{_MODULE}.run_command")


@pytest.fixture
def mock_run_command_sudo(mocker) -> MagicMock:
    return mocker.patch(_PATCH_RUN_COMMAND_SUDO)


# ---------------------------------------------------------------------------
# check_pacman_database
# ---------------------------------------------------------------------------


class TestCheckPacmanDatabase:
    def test_returns_false_when_pacman_not_available(self, mocker):
        mocker.patch(_PATCH_CHECK_COMMAND, return_value=False)
        is_healthy, msg = check_pacman_database()
        assert not is_healthy
        assert "not found" in msg

    def test_returns_false_when_database_check_fails(self, mocker, mock_run_command: MagicMock):
        mocker.patch(_PATCH_CHECK_COMMAND, return_value=True)

        mock_run_command.return_value = MockResult(success=False, stderr="data corrupted")

        is_healthy, msg = check_pacman_database()
        assert not is_healthy
        assert "integrity check failed" in msg
        assert "corrupted" in msg

    def test_returns_true_when_database_check_succeeds(self, mocker, mock_run_command: MagicMock):
        mocker.patch(_PATCH_CHECK_COMMAND, return_value=True)

        mock_run_command.return_value = MockResult(success=True)

        is_healthy, msg = check_pacman_database()
        assert is_healthy
        assert "database healthy" in msg


# ---------------------------------------------------------------------------
# check_package_files
# ---------------------------------------------------------------------------


class TestCheckPackageFiles:
    def test_returns_false_when_pacman_not_available(self, mocker):
        mocker.patch(_PATCH_CHECK_COMMAND, return_value=False)
        all_present, msg = check_package_files()
        assert not all_present
        assert "not found" in msg

    def test_returns_false_when_check_command_fails(self, mocker, mock_run_command_sudo: MagicMock):
        mocker.patch(_PATCH_CHECK_COMMAND, return_value=True)
        mock_run_command_sudo.return_value = MockResult(
            success=False, stderr="error: failed to read database"
        )

        all_present, msg = check_package_files()
        assert not all_present
        assert "file check failed" in msg
        assert "failed to read database" in msg

    def test_returns_true_when_all_package_files_present(
        self, mocker, mock_run_command_sudo: MagicMock
    ):
        mocker.patch(_PATCH_CHECK_COMMAND, return_value=True)

        mock_stdout = (
            "linux: 1000 total files, 0 missing files\nsystemd: 500 total files, 0 missing files\n"
        )
        mock_run_command_sudo.return_value = MockResult(success=True, stdout=mock_stdout)

        all_present, msg = check_package_files()
        assert all_present
        assert "files are present" in msg

    def test_returns_true_when_no_packages_are_installed(self, mocker):
        mocker.patch(_PATCH_CHECK_COMMAND, return_value=True)
        mocker.patch(
            _PATCH_RUN_COMMAND_SUDO,
            return_value=MockResult(success=True, stdout=""),
        )

        all_present, msg = check_package_files()
        assert all_present
        assert "files are present" in msg

    def test_returns_false_when_package_files_missing(
        self, mocker, mock_run_command_sudo: MagicMock
    ):
        mocker.patch(_PATCH_CHECK_COMMAND, return_value=True)

        mock_stdout = (
            "linux: 1000 total files, 0 missing files\n"
            "systemd: 500 total files, 2 missing files\n"
            "glibc: 300 total files, 0 missing files\n"
            "pacman: 100 total files, 1 missing files\n"
        )
        mock_run_command_sudo.return_value = MockResult(success=True, stdout=mock_stdout)

        all_present, msg = check_package_files()
        assert not all_present
        assert "Missing files found:" in msg
        assert "systemd: 500 total files, 2 missing files" in msg
        assert "pacman: 100 total files, 1 missing files" in msg
        assert "linux" not in msg
        assert "glibc" not in msg


# ---------------------------------------------------------------------------
# get_pending_repo_updates
# ---------------------------------------------------------------------------


class TestGetPendingRepoUpdates:
    def test_parses_pending_updates(self, mock_run_command: MagicMock):
        mock_run_command.return_value = _result(
            stdout="linux 6.10.1.arch1-1 -> 6.10.2.arch1-1\npacman 7.0.0-1 -> 7.1.0-1"
        )

        updates = get_pending_repo_updates()

        assert [u.name for u in updates] == ["linux", "pacman"]
        assert updates[0].old_version == "6.10.1.arch1-1"
        assert updates[0].new_version == "6.10.2.arch1-1"

    def test_no_updates_returns_empty_list(self, mock_run_command: MagicMock):
        mock_run_command.return_value = _result(
            "checkupdates", stdout="no updates available", returncode=2, success=True
        )
        assert get_pending_repo_updates() == []

    def test_unexpected_failure_raises(self, mock_run_command: MagicMock):
        """Exit 1 is an unknown failure and must not masquerade as "nothing to do"."""
        mock_run_command.return_value = _result(stderr="could not resolve host", returncode=1)

        with pytest.raises(OSError, match="checkupdates failed"):
            get_pending_repo_updates()

    def test_requests_nocolor_output(self, mock_run_command: MagicMock):
        """A colorised pacman.conf would otherwise inject ANSI escapes into the versions."""
        mock_run_command.return_value = _result()

        get_pending_repo_updates()

        assert mock_run_command.call_args.args[0] == ["checkupdates", "--nocolor"]


# ---------------------------------------------------------------------------
# parse_pending_updates
# ---------------------------------------------------------------------------


class TestParsePendingUpdates:
    def test_parses_multiple_lines(self):
        updates = parse_pending_updates(
            "linux 6.10.1.arch1-1 -> 6.10.2.arch1-1\nneovim-git 0.10.0.r1 -> 0.10.0.r2"
        )
        EXPECTED_UPDATE_COUNT = 2

        assert len(updates) == EXPECTED_UPDATE_COUNT
        assert updates[0].name == "linux"
        assert updates[1].name == "neovim-git"
        assert updates[1].old_version == "0.10.0.r1"
        assert updates[1].new_version == "0.10.0.r2"

    def test_blank_output_yields_no_updates(self):
        assert parse_pending_updates("") == []

    @pytest.mark.parametrize(
        "line",
        [
            "banner text with no arrow",
            "linux -> 2.0",  # missing the installed version
            "linux 1.0 extra -> 2.0",  # more than two fields before the arrow
            " -> ",
        ],
    )
    def test_unrecognised_lines_are_skipped(self, line):
        assert parse_pending_updates(line) == []

    def test_valid_lines_survive_surrounding_noise(self):
        updates = parse_pending_updates(
            "warning: something\nlinux 1.0 -> 2.0\n\nanother stray line\n"
        )

        assert [u.name for u in updates] == ["linux"]


# ---------------------------------------------------------------------------
# snapshot_package_manifest
# ---------------------------------------------------------------------------


class TestSnapshotPackageManifest:
    def test_writes_manifest_and_returns_destination(
        self, tmp_path: Path, mock_run_command: MagicMock
    ):
        mock_run_command.return_value = _result(stdout="linux 6.10.1\npacman 7.0.0")
        destination = tmp_path / "nested" / "manifest.txt"

        result = snapshot_package_manifest(destination)

        assert result == destination
        assert destination.read_text(encoding="utf-8") == "linux 6.10.1\npacman 7.0.0\n"

    def test_raises_when_query_fails(self, tmp_path: Path, mock_run_command: MagicMock):
        mock_run_command.return_value = _result(stderr="database is locked", returncode=1)

        with pytest.raises(OSError, match="package manifest"):
            snapshot_package_manifest(tmp_path / "manifest.txt")

    def test_empty_manifest_is_allowed(self, tmp_path: Path, mock_run_command: MagicMock):
        mock_run_command.return_value = _result(stdout="")
        destination = tmp_path / "manifest.txt"

        snapshot_package_manifest(destination)

        assert destination.read_text(encoding="utf-8") == "\n"


# ---------------------------------------------------------------------------
# diff_manifests
# ---------------------------------------------------------------------------


class TestDiffManifests:
    def test_returns_packages_absent_from_after(self, tmp_path: Path):
        before = _write(tmp_path / "before", "linux 6.1\nexpat 2.0\npacman 7.0")
        after = _write(tmp_path / "after", "linux 6.2\npacman 7.1")

        assert diff_manifests(before, after) == ["expat"]

    def test_version_changes_are_not_removals(self, tmp_path: Path):
        before = _write(tmp_path / "before", "linux 6.1")
        after = _write(tmp_path / "after", "linux 6.2")

        assert diff_manifests(before, after) == []

    def test_output_is_sorted(self, tmp_path: Path):
        before = _write(tmp_path / "before", "zeta 1.0\nlinux 6.1\nalpha 2.0")
        after = _write(tmp_path / "after", "linux 6.2")

        assert diff_manifests(before, after) == ["alpha", "zeta"]

    def test_missing_manifest_raises(self, tmp_path: Path):
        with pytest.raises(OSError, match="nope"):
            diff_manifests(tmp_path / "nope", tmp_path / "nope")


# ---------------------------------------------------------------------------
# backup_sync_db
# ---------------------------------------------------------------------------


class TestBackupSyncDb:
    def test_copies_sync_db_into_timestamped_directory(
        self, tmp_path: Path, mock_run_command_sudo: MagicMock, mocker
    ):
        sync_path = tmp_path / "sync"
        sync_path.mkdir()
        mocker.patch(_PATCH_SYNC_DB, sync_path)
        destination_dir = tmp_path / "backups"

        backup_path = backup_sync_db(destination_dir)

        assert backup_path.parent == destination_dir
        assert backup_path.name.startswith("sync-db_")
        assert mock_run_command_sudo.call_args.args[0] == [
            "cp",
            "-a",
            str(sync_path),
            str(backup_path),
        ]

    def test_raises_when_sync_db_missing(
        self, tmp_path: Path, mock_run_command_sudo: MagicMock, mocker
    ):
        mocker.patch(_PATCH_SYNC_DB, tmp_path / "does-not-exist")

        with pytest.raises(OSError, match="sync database directory not found"):
            backup_sync_db(tmp_path)

        mock_run_command_sudo.assert_not_called()

    def test_raises_when_copy_fails(self, tmp_path: Path, mock_run_command_sudo: MagicMock, mocker):
        sync_path = tmp_path / "sync"
        sync_path.mkdir()
        mocker.patch(_PATCH_SYNC_DB, sync_path)
        mock_run_command_sudo.side_effect = CalledProcessError(1, "cp")

        with pytest.raises(OSError, match="Could not back up"):
            backup_sync_db(tmp_path / "backups")


# ---------------------------------------------------------------------------
# restore_sync_db
# ---------------------------------------------------------------------------


class TestRestoreSyncDb:
    def test_merges_backup_contents_over_sync_db(
        self, tmp_path: Path, mock_run_command_sudo: MagicMock, mocker
    ):
        backup = tmp_path / "sync-db_2026-01-01_000000"
        backup.mkdir()
        sync_path = tmp_path / "sync"
        sync_path.mkdir()
        mocker.patch(_PATCH_SYNC_DB, sync_path)

        restore_sync_db(backup)

        assert mock_run_command_sudo.call_args.args[0] == [
            "cp",
            "-a",
            f"{backup}/.",
            f"{sync_path}/",
        ]

    def test_raises_when_backup_missing(self, tmp_path: Path, mock_run_command_sudo: MagicMock):
        with pytest.raises(OSError, match="does not exist"):
            restore_sync_db(tmp_path / "nope")

        mock_run_command_sudo.assert_not_called()

    def test_raises_when_copy_fails(self, tmp_path: Path, mock_run_command_sudo: MagicMock):
        backup = tmp_path / "sync-db_2026-01-01_000000"
        backup.mkdir()
        mock_run_command_sudo.side_effect = CalledProcessError(1, "cp")

        with pytest.raises(OSError, match="Could not restore"):
            restore_sync_db(backup)


# ---------------------------------------------------------------------------
# run_system_upgrade
# ---------------------------------------------------------------------------


class TestRunSystemUpgrade:
    def test_runs_pacman_syu_with_inherited_stdio(self, mock_run_command_sudo: MagicMock):
        mock_run_command_sudo.return_value = _result()

        run_system_upgrade()

        assert mock_run_command_sudo.call_args.args[0] == ["pacman", "-Syu"]
        options = mock_run_command_sudo.call_args.kwargs["options"]
        assert options.capture_output is False

    def test_does_not_pass_noconfirm(self, mock_run_command_sudo: MagicMock):
        """pacman's own prompt is the only place pending removals and conflicts surface."""
        mock_run_command_sudo.return_value = _result()

        run_system_upgrade()

        assert "--noconfirm" not in mock_run_command_sudo.call_args.args[0]


# ---------------------------------------------------------------------------
# clean_cache
# ---------------------------------------------------------------------------


class TestCleanCache:
    def test_issues_two_paccache_invocations(
        self, tmp_path: Path, mock_run_command_sudo: MagicMock
    ):
        """paccache applies one --keep per run, so installed and uninstalled need two passes."""
        cache_dir = tmp_path / "pkg"
        cache_dir.mkdir()
        mock_run_command_sudo.return_value = _result()

        clean_cache(keep=3, keep_uninstalled=0, cache_dir=cache_dir)

        commands = [call.args[0] for call in mock_run_command_sudo.call_args_list]
        assert commands == [
            ["paccache", "-r", "-k", "3", "-c", str(cache_dir)],
            ["paccache", "-r", "-u", "-k", "0", "-c", str(cache_dir)],
        ]

    def test_returns_bytes_freed(self, tmp_path: Path, mock_run_command_sudo: MagicMock):
        CACHE_BYTES = 100
        cache_dir = tmp_path / "pkg"
        cache_dir.mkdir()
        stale = cache_dir / "stale.pkg.tar.zst"
        stale.write_bytes(b"x" * CACHE_BYTES)
        (cache_dir / "keep.pkg.tar.zst").write_bytes(b"y" * 50)

        def _remove_stale(command, options=None):
            stale.unlink(missing_ok=True)
            return _result()

        mock_run_command_sudo.side_effect = _remove_stale

        assert clean_cache(keep=1, keep_uninstalled=0, cache_dir=cache_dir) == CACHE_BYTES

    def test_returns_zero_when_cache_dir_missing(
        self, tmp_path: Path, mock_run_command_sudo: MagicMock
    ):
        mock_run_command_sudo.return_value = _result()

        assert clean_cache(keep=3, keep_uninstalled=0, cache_dir=tmp_path / "nope") == 0

    def test_failures_do_not_raise(self, tmp_path: Path, mock_run_command_sudo: MagicMock):
        """Cleanup runs after a successful upgrade, so it must never fail the task."""
        mock_run_command_sudo.return_value = _result(stderr="permission denied", returncode=1)

        assert clean_cache(keep=3, keep_uninstalled=0, cache_dir=tmp_path) == 0


# ---------------------------------------------------------------------------
# list_pacnew_files
# ---------------------------------------------------------------------------


class TestListPacnewFiles:
    def test_parses_newline_separated_paths(self, mock_run_command: MagicMock):
        mock_run_command.return_value = _result(
            stdout="/etc/pacman.conf.pacnew\n/etc/mkinitcpio.conf.pacnew"
        )

        assert list_pacnew_files() == [
            "/etc/pacman.conf.pacnew",
            "/etc/mkinitcpio.conf.pacnew",
        ]

    def test_parses_space_separated_paths(self, mock_run_command: MagicMock):
        """pacdiff's separator is undocumented, so both shapes must work."""
        mock_run_command.return_value = _result(stdout="/etc/a.pacnew /etc/b.pacnew")

        assert list_pacnew_files() == ["/etc/a.pacnew", "/etc/b.pacnew"]

    def test_ignores_non_path_output(self, mock_run_command: MagicMock):
        mock_run_command.return_value = _result(stdout="==> WARNING: something odd\n/etc/a.pacnew")

        assert list_pacnew_files() == ["/etc/a.pacnew"]

    def test_returns_empty_on_failure(self, mock_run_command: MagicMock):
        mock_run_command.return_value = _result(stderr="pacdiff not found", returncode=1)

        assert list_pacnew_files() == []

    def test_uses_print_only_mode(self, mock_run_command: MagicMock):
        mock_run_command.return_value = _result()

        list_pacnew_files()

        assert mock_run_command.call_args.args[0] == ["pacdiff", "-o", "--nocolor"]
