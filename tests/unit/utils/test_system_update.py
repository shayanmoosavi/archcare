"""Unit tests for AUR, Arch news, and Btrfs snapshot utility functions."""

import shlex
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from archcare.utils.system import CommandResult
from archcare.utils.system_update import (
    build_restore_script,
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


# ---------------------------------------------------------------------------
# build_restore_script
# ---------------------------------------------------------------------------

_BACKUP = Path("/r/sync-db/b")
_CACHE = Path("/tmp/cache")


def _script(**kwargs) -> str:
    """Render the restore script with sensible defaults for the paths under test."""
    kwargs.setdefault("sync_db_backup", _BACKUP)
    kwargs.setdefault("cache_dir", _CACHE)
    return build_restore_script(**kwargs)


class TestBuildRestoreScriptPaths:
    def test_script_embeds_the_backup_path(self):
        script = _script()

        assert shlex.quote(str(_BACKUP)) in script

    def test_script_embeds_the_cache_and_sync_target(self):
        script = _script()

        assert shlex.quote(str(_CACHE)) in script
        assert shlex.quote("/var/lib/pacman/sync") in script

    def test_default_cache_dir_is_the_pacman_cache(self):
        script = build_restore_script(_BACKUP)

        assert shlex.quote("/var/cache/pacman/pkg") in script

    def test_quotes_paths_with_shell_metacharacters(self):
        """The backup path is untrusted file content — no bare interpolation."""
        hostile = Path('/r/we\'ird $(touch pwned) "; rm -rf /; echo " dir/bk')
        script = _script(sync_db_backup=hostile)

        assert shlex.quote(str(hostile)) in script
        # The raw, unquoted form must not appear as a bare assignment value.
        assignment = next(line for line in script.splitlines() if line.startswith("SYNC_BACKUP="))
        assert assignment == f"SYNC_BACKUP={shlex.quote(str(hostile))}"


class TestBuildRestoreScriptWikiMethod:
    def test_script_does_not_reference_the_manifest_at_all(self):
        """The canonical method needs no manifest — pacman reads the restored sync DB itself."""
        script = _script()

        assert "MANIFEST" not in script
        assert "pacman -Qi" not in script
        assert "awk" not in script

    def test_script_uses_the_wiki_native_restore_command(self):
        script = _script()

        assert "pacman -S -" in script

    def test_native_restore_covers_the_explicitly_installed_set(self):
        """`-Qe`, not `-Qnq`: dependencies return as dependencies, and it is ~6x less work."""
        script = _script()

        assert "# pacman -Qe | sudo pacman -S -" in script

    def test_script_handles_foreign_packages_separately(self):
        """`-S` resolves from sync DBs; AUR packages are not in them."""
        script = _script()

        assert "# pacman -Qmq" in script

    def test_needed_is_explained_and_never_passed_to_pacman(self):
        """`--needed` skips anything the restored DB already lists as current — the majority."""
        script = _script()

        assert "--needed" in script, "its absence must be explained, not silent"
        offending = [
            line for line in script.splitlines() if "--needed" in line and "pacman" in line
        ]
        assert offending == [], f"--needed must never reach a command line: {offending}"

    def test_script_documents_the_sync_db_dependency(self):
        """Without the restored sync DB the `-S` command installs NEWER packages, not older ones."""
        script = _script()

        assert "sync" in script.lower()
        assert "Restoring pacman sync database" in script


class TestBuildRestoreScriptPrecondition:
    def test_sync_backup_guard_precedes_the_copy(self):
        """The guard is the whole critical-failure contract: check first, copy second."""
        script = _script(sync_db_backup=Path("/r/nope"))

        assert script.index("exit 1") < script.index("cp -a")

    def test_the_sync_backup_guard_itself_exits_before_the_copy(self):
        """Scoped to the sync-backup block: an unrelated earlier `exit 1` must not satisfy it."""
        script = _script()

        start = script.index('if [ ! -d "$SYNC_BACKUP" ]; then')
        block = script[start : script.index("\nfi", start)]

        assert "exit 1" in block, "the sync-backup guard must abort, not fall through"
        assert start < script.index("cp -a")

    def test_guard_tests_for_a_directory(self):
        script = _script()

        assert '[ ! -d "$SYNC_BACKUP" ]' in script

    def test_merges_rather_than_wiping_the_sync_db(self):
        """`cp -a <backup>/. <target>/` mirrors restore_sync_db; never `mv` or a wipe-first."""
        script = _script()

        assert 'cp -a "$SYNC_BACKUP/." "$SYNC_TARGET/"' in script
        assert "rm -rf" not in script
        assert "mv " not in script

    def test_script_stops_at_the_first_failing_command(self):
        """`set -euo pipefail`: a failed `cp -a` must abort, not fall through to a bogus restore."""
        script = _script()

        assert "set -euo pipefail" in script
        assert script.index("set -euo pipefail") < script.index("cp -a")


class TestBuildRestoreScriptReport:
    def test_states_the_rotated_out_limitation_rather_than_promising_exact_versions(self):
        """`-S` resolves from the restored DB, so a version rotated out of it is not restored.

        The old contract here was "report missing artifacts and carry on". There are no
        artifacts to report any more, so the equivalent contract is that the script says
        plainly which case it cannot cover, and offers the exact-version route for it.
        """
        script = _script()

        assert "rotated out" in script
        assert "NOT be downgraded" in script
        assert "pacman -U" in script

    def test_never_runs_the_downgrade_itself(self):
        """Print-only for the destructive step: every `pacman -S` line stays commented.

        The check is on the whole line, not a prefix: the native command is a pipe
        (`pacman -Qe | sudo pacman -S -`), so uncommenting it does not produce a line that
        *starts* with `sudo pacman -S` and a prefix check would sail straight past it.
        """
        script = _script()

        assert "# pacman -Qe | sudo pacman -S -" in script
        uncommented = [
            line
            for line in script.splitlines()
            if "sudo pacman -S" in line and not line.startswith("#")
        ]
        assert uncommented == []


class TestBuildRestoreScriptSyntax:
    def test_generated_script_is_syntactically_valid_bash(self):
        """A syntax error here ships a recovery tool that cannot run at all."""
        script = _script()

        result = subprocess.run(
            ["bash", "-n"],
            input=script,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
