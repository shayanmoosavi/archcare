"""Unit tests for mirrorlist utility functions."""

from datetime import datetime
from pathlib import Path
from subprocess import CalledProcessError
from unittest.mock import MagicMock

import pytest

from archcare.utils.mirrorlist import (
    backup_file,
    get_mirrorlist_info,
    restore_backup,
    update_mirrorlist,
    validate_mirrorlist,
)
from archcare.utils.system import CommandResult

_PATCH_IS_ROOT = "archcare.utils.system.is_root"
_PATCH_CHECK_COMMAND = "archcare.utils.mirrorlist.check_command_exists"
_PATCH_RUN_SUDO = "archcare.utils.mirrorlist.run_command_with_sudo"


# ---------------------------------------------------------------------------
# Helpers and Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def write_src_file(tmp_path) -> Path:
    src: Path = tmp_path / "source_file"
    src.write_text("source file contents\n")
    return src


def _reflector_result(success: bool = True) -> CommandResult:
    return CommandResult(
        command="reflector",
        returncode=0 if success else 1,
        stdout="",
        stderr="",
        success=success,
    )


# ---------------------------------------------------------------------------
# validate_mirrorlist
# ---------------------------------------------------------------------------


class TestValidateMirrorlist:
    def test_returns_false_if_file_missing(self, tmp_path):
        is_valid, msg = validate_mirrorlist(tmp_path / "missing_mirrorlist")
        assert is_valid is False
        assert "does not exist" in msg

    def test_returns_false_if_file_empty(self, tmp_path):
        empty_file: Path = tmp_path / "empty"
        empty_file.touch()

        is_valid, msg = validate_mirrorlist(empty_file)
        assert is_valid is False
        assert "empty" in msg.lower()

    def test_returns_false_if_no_active_servers(self, tmp_path):
        no_servers: Path = tmp_path / "no_servers"
        no_servers.write_text("# Server = https://mirror.example.com\n# Just comments")

        is_valid, msg = validate_mirrorlist(no_servers)
        assert is_valid is False
        assert "No valid mirror" in msg

    def test_returns_true_for_valid_mirrorlist(self, tmp_path):
        valid_file: Path = tmp_path / "valid"
        valid_file.write_text(
            "Server = https://mirror1.com/$repo/os/$arch\n"
            "Server = http://mirror2.com/$repo/os/$arch\n"
        )

        is_valid, msg = validate_mirrorlist(valid_file)
        assert is_valid is True
        assert "2 mirrors" in msg

    def test_indented_server_lines_are_counted(self, tmp_path):
        """
        The implementation strips each line before checking the
        "Server = " prefix, so leading whitespace (spaces or tabs) must
        not cause a valid entry to be skipped.
        """
        indented_file: Path = tmp_path / "indented"
        indented_file.write_text(
            "    Server = https://mirror1.com/$repo/os/$arch\n"
            "\tServer = http://mirror2.com/$repo/os/$arch\n"
        )

        is_valid, msg = validate_mirrorlist(indented_file)
        assert is_valid is True
        assert "2 mirrors" in msg


# ---------------------------------------------------------------------------
# get_mirrorlist_info
# ---------------------------------------------------------------------------


class TestGetMirrorlistInfo:
    def test_returns_defaults_if_missing(self, tmp_path):
        info = get_mirrorlist_info(tmp_path / "missing")
        assert info["total_mirrors"] == 0
        assert info["protocols"] == set()
        assert info["last_modified"] is None

    def test_extracts_protocols_and_counts(self, tmp_path):
        mirrorlist: Path = tmp_path / "mirrorlist"
        mirrorlist.write_text(
            "Server = https://mirror1.com\n"
            "Server = http://mirror2.com\n"
            "Server = rsync://mirror3.com\n"
            "# Server = ftp://ignored.com\n"
            "Server = https://mirror4.com\n"
        )

        info = get_mirrorlist_info(mirrorlist)

        assert info["total_mirrors"] == 4
        # Ensure protocols aren't duplicated
        assert info["protocols"] == {"https", "http", "rsync"}
        # Ensure timestamp was generated
        assert info["last_modified"] is not None

    def test_unrecognized_protocol_counted_but_not_categorized(self, tmp_path):
        mirrorlist: Path = tmp_path / "mirrorlist"
        mirrorlist.write_text(
            "Server = https://mirror1.com\nServer = ftp://mirror2.com\n"
        )

        info = get_mirrorlist_info(mirrorlist)

        assert info["total_mirrors"] == 2
        assert info["protocols"] == {"https"}


# ---------------------------------------------------------------------------
# backup_file
# ---------------------------------------------------------------------------


class TestBackupFile:
    def test_raises_io_error_if_source_missing(self, tmp_path):
        with pytest.raises(IOError):
            backup_file(tmp_path / "missing")

    def test_creates_backup_with_default_suffix(
        self, monkeypatch, write_src_file: Path
    ):
        """
        is_root() is mocked so run_command_with_sudo skips prepending
        'sudo' (which would hang/fail without a real privilege escalation
        in a test environment) - the actual `cp` subprocess still runs for
        real against tmp_path, so this also confirms the backup's content
        matches the source rather than just "some file got created".
        """
        monkeypatch.setattr(_PATCH_IS_ROOT, lambda: True)
        source = write_src_file
        backup_path = backup_file(source)

        assert backup_path.exists()
        assert backup_path.read_text() == source.read_text()
        assert backup_path.name.endswith(".backup")

    def test_creates_backup_with_custom_suffix(self, monkeypatch, write_src_file: Path):
        monkeypatch.setattr(_PATCH_IS_ROOT, lambda: True)
        source = write_src_file
        backup_path = backup_file(source, backup_suffix=".bak")

        assert backup_path.read_text() == source.read_text()
        assert backup_path.name.endswith(".bak")

    def test_backup_filename_includes_source_name_and_timestamp(
        self, monkeypatch, write_src_file: Path
    ):
        monkeypatch.setattr(_PATCH_IS_ROOT, lambda: True)
        source = write_src_file
        backup_path = backup_file(source, backup_suffix=".bak")

        assert "source_file_" in backup_path.name
        assert datetime.now().strftime("%Y-%m-%d") in backup_path.name

    def test_wraps_called_process_error_as_io_error(
        self, monkeypatch, write_src_file: Path
    ):
        source = write_src_file

        # Simulate a CalledProcessError being raised by run_command_with_sudo
        monkeypatch.setattr(
            _PATCH_RUN_SUDO, MagicMock(side_effect=CalledProcessError(1, "cp"))
        )

        with pytest.raises(IOError):
            backup_file(source)


# ---------------------------------------------------------------------------
# restore_backup
# ---------------------------------------------------------------------------


class TestRestoreBackup:
    def test_raises_io_error_if_backup_missing(self, tmp_path):
        with pytest.raises(IOError):
            restore_backup(tmp_path / "missing.backup", tmp_path / "target")

    def test_restores_content_to_target(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_PATCH_IS_ROOT, lambda: True)
        backup: Path = tmp_path / "target.backup"
        backup.write_text("backed up content\n")
        target: Path = tmp_path / "target"
        target.write_text("messed up content\n")

        restore_backup(backup, target)

        assert target.read_text() == backup.read_text()

    def test_wraps_called_process_error_as_io_error(self, tmp_path, monkeypatch):
        backup: Path = tmp_path / "target.backup"
        backup.write_text("backed up content\n")

        monkeypatch.setattr(
            _PATCH_RUN_SUDO, MagicMock(side_effect=CalledProcessError(1, "cp"))
        )

        with pytest.raises(IOError):
            restore_backup(backup, tmp_path / "target")


# ---------------------------------------------------------------------------
# update_mirrorlist
# ---------------------------------------------------------------------------


class TestUpdateMirrorlist:
    def test_raises_when_reflector_not_found(self, monkeypatch):
        monkeypatch.setattr(_PATCH_CHECK_COMMAND, lambda _: False)

        with pytest.raises(RuntimeError):
            update_mirrorlist()

    def test_builds_command_with_string_country_and_protocol(self, monkeypatch):
        monkeypatch.setattr(_PATCH_CHECK_COMMAND, lambda _: True)
        mock_run = MagicMock(return_value=_reflector_result())
        monkeypatch.setattr(_PATCH_RUN_SUDO, mock_run)

        update_mirrorlist(country="Germany", protocol="https")

        cmd = mock_run.call_args[0][0]
        assert "--country" in cmd and "Germany" in cmd
        assert "--protocol" in cmd and "https" in cmd

    def test_builds_command_with_list_country_and_protocol(self, monkeypatch):
        """Lists are comma-joined into a single reflector argument."""
        monkeypatch.setattr(_PATCH_CHECK_COMMAND, lambda _: True)
        mock_run = MagicMock(return_value=_reflector_result())
        monkeypatch.setattr(_PATCH_RUN_SUDO, mock_run)

        update_mirrorlist(country=["Germany", "France"], protocol=["https", "http"])

        cmd = mock_run.call_args[0][0]
        assert "Germany,France" in cmd
        assert "https,http" in cmd

    def test_omits_country_and_protocol_when_not_given(self, monkeypatch):
        monkeypatch.setattr(_PATCH_CHECK_COMMAND, lambda _: True)
        mock_run = MagicMock(return_value=_reflector_result())
        monkeypatch.setattr(_PATCH_RUN_SUDO, mock_run)

        update_mirrorlist(country=None, protocol=None)

        cmd = mock_run.call_args[0][0]
        assert "--country" not in cmd
        assert "--protocol" not in cmd

    def test_includes_save_path_when_given(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_PATCH_CHECK_COMMAND, lambda _: True)
        mock_run = MagicMock(return_value=_reflector_result())
        monkeypatch.setattr(_PATCH_RUN_SUDO, mock_run)

        save_path: Path = tmp_path / "mirrorlist"
        update_mirrorlist(save_path=save_path)

        cmd = mock_run.call_args[0][0]
        assert "--save" in cmd and str(save_path) in cmd

    def test_omits_save_path_when_not_given(self, monkeypatch):
        monkeypatch.setattr(_PATCH_CHECK_COMMAND, lambda _: True)
        mock_run = MagicMock(return_value=_reflector_result())
        monkeypatch.setattr(_PATCH_RUN_SUDO, mock_run)

        update_mirrorlist()

        cmd = mock_run.call_args[0][0]
        assert "--save" not in cmd

    def test_timeout_formula_matches_latest_value(self, monkeypatch):
        """cmd_timeout = latest * 5 + 30 seconds of padding."""
        monkeypatch.setattr(_PATCH_CHECK_COMMAND, lambda _: True)
        mock_run = MagicMock(return_value=_reflector_result())
        monkeypatch.setattr(_PATCH_RUN_SUDO, mock_run)

        update_mirrorlist(latest=10)

        assert mock_run.call_args.kwargs["timeout"] == 10 * 5 + 30

    def test_returns_command_result_from_run_sudo(self, monkeypatch):
        monkeypatch.setattr(_PATCH_CHECK_COMMAND, lambda _: True)
        expected = _reflector_result()
        monkeypatch.setattr(_PATCH_RUN_SUDO, MagicMock(return_value=expected))

        result = update_mirrorlist()

        assert result is expected
