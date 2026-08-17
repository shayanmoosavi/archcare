"""Unit tests for pacman utility functions."""

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from archcare.utils.pacman import check_package_files, check_pacman_database

_MODULE = "archcare.utils.pacman"

_PATCH_CHECK_COMMAND = f"{_MODULE}.check_command_exists"
_PATCH_RUN_COMMAND_SUDO = f"{_MODULE}.run_command_with_sudo"

# ---------------------------------------------------------------------------
# Fixtures and Helpers
# ---------------------------------------------------------------------------


@dataclass
class MockResult:
    """Helper to simulate the CommandResult dataclass"""

    success: bool = True
    stdout: str = ""
    stderr: str = ""


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

    def test_returns_false_when_database_check_fails(self, mocker, mock_run_command):
        mocker.patch(_PATCH_CHECK_COMMAND, return_value=True)

        mock_run_command.return_value = MockResult(success=False, stderr="data corrupted")

        is_healthy, msg = check_pacman_database()
        assert not is_healthy
        assert "integrity check failed" in msg
        assert "corrupted" in msg

    def test_returns_true_when_database_check_succeeds(self, mocker, mock_run_command):
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
