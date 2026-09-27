"""Unit tests for AUR, Arch news, and Btrfs snapshot utility functions."""

from unittest.mock import MagicMock

import pytest

from archcare.utils.system import CommandResult
from archcare.utils.system_update import (
    detect_btrfs_snapshot_tooling,
    get_latest_snapshot_id,
    get_pending_aur_updates,
    has_unread_arch_news,
    run_aur_upgrade,
)

_MODULE = "archcare.utils.system_update"

_PATCH_CHECK_COMMAND = f"{_MODULE}.check_command_exists"
_PATCH_RUN_COMMAND = f"{_MODULE}.run_command"
_PATCH_RUN_COMMAND_SUDO = f"{_MODULE}.run_command_with_sudo"

# ---------------------------------------------------------------------------
# Fixtures and Helpers
# ---------------------------------------------------------------------------


def _result(stdout: str = "", stderr: str = "", returncode: int = 0) -> CommandResult:
    """Build a real `CommandResult`, deriving `success` from the exit code."""
    return CommandResult(
        command="test",
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        success=returncode == 0,
    )


@pytest.fixture
def mock_check_command(mocker) -> MagicMock:
    return mocker.patch(_PATCH_CHECK_COMMAND)


@pytest.fixture
def mock_run_command(mocker) -> MagicMock:
    return mocker.patch(_PATCH_RUN_COMMAND)


@pytest.fixture
def mock_run_command_sudo(mocker) -> MagicMock:
    return mocker.patch(_PATCH_RUN_COMMAND_SUDO)


@pytest.fixture
def mock_package_installed(mocker) -> MagicMock:
    return mocker.patch(f"{_MODULE}.is_package_installed")


# ---------------------------------------------------------------------------
# has_unread_arch_news
# ---------------------------------------------------------------------------


class TestHasUnreadArchNews:
    def test_returns_false_when_informant_missing(
        self, mock_check_command: MagicMock, mock_run_command: MagicMock
    ):
        mock_check_command.return_value = False

        assert has_unread_arch_news() is False
        mock_run_command.assert_not_called()

    def test_returns_true_when_unread_news_is_listed(
        self, mock_check_command: MagicMock, mock_run_command: MagicMock
    ):
        mock_check_command.return_value = True
        mock_run_command.return_value = _result(
            stdout="New kernel requires manual intervention before rebooting"
        )

        assert has_unread_arch_news() is True

    def test_returns_false_when_nothing_is_unread(
        self, mock_check_command: MagicMock, mock_run_command: MagicMock
    ):
        mock_check_command.return_value = True
        mock_run_command.return_value = _result(stdout="")

        assert has_unread_arch_news() is False

    def test_uses_read_only_list_command(
        self, mock_check_command: MagicMock, mock_run_command: MagicMock
    ):
        """`informant check` marks a lone unread item as read — it must never be used here."""
        mock_check_command.return_value = True
        mock_run_command.return_value = _result()

        has_unread_arch_news()

        assert mock_run_command.call_args.args[0] == ["informant", "list", "--unread"]

    def test_fails_open_when_informant_errors(
        self, mock_check_command: MagicMock, mock_run_command: MagicMock
    ):
        """An undeterminable news state must not block an otherwise safe update."""
        mock_check_command.return_value = True
        mock_run_command.return_value = _result(stderr="network unreachable", returncode=1)

        assert has_unread_arch_news() is False


# ---------------------------------------------------------------------------
# get_pending_aur_updates
# ---------------------------------------------------------------------------


class TestGetPendingAurUpdates:
    def test_parses_pending_updates(self, mock_run_command: MagicMock):
        mock_run_command.return_value = _result(
            stdout="paru 2.0.0-1 -> 2.0.1-1\nneovim-git 0.10.0.r1 -> 0.10.0.r2"
        )

        updates = get_pending_aur_updates()

        assert [u.name for u in updates] == ["paru", "neovim-git"]
        assert updates[0].old_version == "2.0.0-1"
        assert updates[0].new_version == "2.0.1-1"

    def test_empty_output_means_no_updates(self, mock_run_command: MagicMock):
        """paru -Qua wraps pacman -Qu, which prints nothing and exits non-zero when idle."""
        mock_run_command.return_value = _result(returncode=1)

        assert get_pending_aur_updates() == []

    def test_does_not_raise_on_failure(self, mock_run_command: MagicMock):
        """A broken AUR query must not block the repository half of the update."""
        mock_run_command.return_value = _result(stderr="AUR unreachable", returncode=1)

        assert get_pending_aur_updates() == []

    def test_uses_aur_only_query(self, mock_run_command: MagicMock):
        mock_run_command.return_value = _result()

        get_pending_aur_updates()

        assert mock_run_command.call_args.args[0] == ["paru", "-Qua"]


# ---------------------------------------------------------------------------
# run_aur_upgrade
# ---------------------------------------------------------------------------


class TestRunAurUpgrade:
    def test_runs_paru_sua_without_sudo(
        self, mock_run_command: MagicMock, mock_run_command_sudo: MagicMock
    ):
        """paru refuses to build AUR packages as root, so no sudo prefixing here."""
        mock_run_command.return_value = _result()

        run_aur_upgrade()

        assert mock_run_command.call_args.args[0] == ["paru", "-Sua"]
        mock_run_command_sudo.assert_not_called()

    def test_inherits_stdio(self, mock_run_command: MagicMock):
        """paru's own diff review needs the real terminal."""
        mock_run_command.return_value = _result()

        run_aur_upgrade()

        options = mock_run_command.call_args.kwargs["options"]
        assert options.capture_output is False


# ---------------------------------------------------------------------------
# detect_btrfs_snapshot_tooling
# ---------------------------------------------------------------------------


class TestDetectBtrfsSnapshotTooling:
    def test_true_when_both_packages_are_installed(
        self, mock_check_command: MagicMock, mock_package_installed: MagicMock
    ):
        mock_check_command.return_value = True
        mock_package_installed.return_value = True

        assert detect_btrfs_snapshot_tooling() is True

    def test_is_package_installed_called_twice_with_correct_args(
        self, mock_check_command: MagicMock, mock_package_installed: MagicMock
    ):
        mock_check_command.return_value = True
        mock_package_installed.return_value = True

        EXPECTED_CALL_COUNT = 2
        detect_btrfs_snapshot_tooling()

        assert mock_package_installed.call_count == EXPECTED_CALL_COUNT
        assert mock_package_installed.call_args_list[0].args[0] == "snap-pac"
        assert mock_package_installed.call_args_list[1].args[0] == "grub-btrfs"

    @pytest.mark.parametrize("missing", ["snap-pac", "grub-btrfs"])
    def test_false_when_either_package_is_missing(
        self, missing: str, mock_check_command: MagicMock, mock_package_installed: MagicMock
    ):
        mock_check_command.return_value = True
        # Return True for the package that's present, False for the missing one
        mock_package_installed.side_effect = lambda pkg: pkg != missing

        # all() short-circuits on first False, so call_count will be 1 if the first
        # package is missing, or 2 if the second package is missing
        assert detect_btrfs_snapshot_tooling() is False
        mock_package_installed.assert_any_call(missing)

    def test_false_when_pacman_is_missing(
        self, mock_check_command: MagicMock, mock_run_command: MagicMock
    ):
        mock_check_command.return_value = False

        assert detect_btrfs_snapshot_tooling() is False
        mock_run_command.assert_not_called()


# ---------------------------------------------------------------------------
# get_latest_snapshot_id
# ---------------------------------------------------------------------------

_CSV_SNAPSHOTS = "number,type\n0,single\n1*,single\n3,pre\n4,post\n5,pre\n6,post\n"
LATEST_SNAPSHOT_ID = 5


class TestGetLatestSnapshotId:
    def test_returns_the_highest_pre_snapshot(self, mock_run_command_sudo: MagicMock):
        mock_run_command_sudo.return_value = _result(stdout=_CSV_SNAPSHOTS)

        assert get_latest_snapshot_id() == LATEST_SNAPSHOT_ID

    def test_uses_machine_readable_output(self, mock_run_command_sudo: MagicMock):
        """The human table decorates the active snapshot number with '*' — parse CSV instead."""
        mock_run_command_sudo.return_value = _result()

        get_latest_snapshot_id()

        assert mock_run_command_sudo.call_args.args[0] == [
            "snapper",
            "--csvout",
            "-c",
            "root",
            "list",
            "--columns",
            "number,type",
        ]

    def test_config_name_is_passed_through(self, mock_run_command_sudo: MagicMock):
        mock_run_command_sudo.return_value = _result()

        get_latest_snapshot_id(config="home")

        command = mock_run_command_sudo.call_args.args[0]
        assert command[command.index("-c") + 1] == "home"

    def test_returns_none_without_pre_snapshots(self, mock_run_command_sudo: MagicMock):
        mock_run_command_sudo.return_value = _result(stdout="number,type\n0,single\n4,post\n")

        assert get_latest_snapshot_id() is None

    def test_returns_none_when_listing_fails(self, mock_run_command_sudo: MagicMock):
        mock_run_command_sudo.return_value = _result(stderr="no such config", returncode=1)

        assert get_latest_snapshot_id() is None

    def test_returns_none_for_empty_output(self, mock_run_command_sudo: MagicMock):
        mock_run_command_sudo.return_value = _result(stdout="")

        assert get_latest_snapshot_id() is None

    def test_unparseable_rows_do_not_abort_the_parse(self, mock_run_command_sudo: MagicMock):
        """A decorated number must be skipped, not allowed to raise mid-listing."""
        mock_run_command_sudo.return_value = _result(
            stdout="number,type\n1*,single\n3,pre\n5,pre\n"
        )

        assert get_latest_snapshot_id() == LATEST_SNAPSHOT_ID
