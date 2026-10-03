"""Unit tests for RecoveryService (services/recovery_service.py)."""

import json
import os
from pathlib import Path
from typing import Any

import pytest
from _pytest.monkeypatch import MonkeyPatch

from archcare.config import AppSettings
from archcare.services.recovery_service import RecoveryService
from archcare.services.responses import RecoveryResponse

# The command shape the plan pins: snapper first, then the restore script, then the
# package-cache pointer. Stated once here so the ordering assertions below do not restate it.
# The script path is matched by substring, never `endswith` — the command carries a trailing
# guidance comment, so a suffix match would never fire.
SNAPSHOT_ID = 42
SNAPPER_COMMAND = f"snapper rollback {SNAPSHOT_ID}"
SCRIPT_PATH = "downgrade.sh"
CACHE_COMMAND = "ls /var/cache/pacman/pkg/  # reinstall a removed package from here"
SINGLE_PACKAGE_INSTALLATION_COMMAND = (
    "# Example installation command:",
    "sudo pacman -U /var/cache/pacman/pkg/[package-name].pkg.tar.zst",
)
EXPECTED_COMMAND_COUNT = 5


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def recovery_settings(tmp_path: Path, monkeypatch: MonkeyPatch) -> AppSettings:
    """An `AppSettings` whose `recovery_dir` resolves inside `tmp_path`.

    `Path.home` is redirected rather than the `recovery_dir` property alone, so `settings` is a
    real, unmodified `AppSettings` and the service resolves the same path the test writes to.
    The autouse `clear_archcare_user` fixture drops `SUDO_USER`/`ARCHCARE_USER`, which is what
    would otherwise make `home_dir` resolve through `pwd` and defeat the redirect.
    """
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    return AppSettings(user=None)


@pytest.fixture
def service(recovery_settings: AppSettings) -> RecoveryService:
    return RecoveryService(recovery_settings)


@pytest.fixture
def record_dir(recovery_settings: AppSettings) -> Path:
    """The directory the service actually reads: `<home>/.local/state/archcare/recovery`.

    The test writes through this rather than guessing a path, so a change to
    `AppSettings.recovery_dir` can never leave the suite testing a directory the service ignores.
    """
    return recovery_settings.recovery_dir


def _write_record(record_dir: Path, **overrides: Any) -> Path:
    """Write a recovery record with the exact ten-key shape the task produces.

    Overrides let a test drop a single key to `None` or empty a list without restating the
    whole record, which is what keeps the gating tests below honest.
    """
    record: dict[str, Any] = {
        "task": "system-update",
        "updated_at": "2026-09-29T18:00:00",
        "sync_db_backup": str(record_dir / "sync-db/backup"),
        "manifest_before": str(record_dir / "manifests/before.txt"),
        "manifest_after": str(record_dir / "manifests/after.txt"),
        "pre_update_snapshot_id": SNAPSHOT_ID,
        "packages_upgraded": ["linux"],
        "aur_packages_upgraded": [],
        "aur_packages_failed": ["yay"],
        "packages_removed": ["linux-lts"],
    }
    record.update(overrides)
    path = record_dir / "system-update.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# RecoveryResponse
# ---------------------------------------------------------------------------


class TestRecoveryResponseDefaults:
    def test_response_defaults_to_no_recovery_available(self):
        response = RecoveryResponse()
        assert response.available is False
        assert response.snapshot_id is None
        assert response.commands == ()

    def test_mutable_defaults_are_not_shared_between_instances(self):
        first = RecoveryResponse()
        first.packages_removed.append("linux-lts")
        first.aur_packages_failed.append("yay")
        assert RecoveryResponse().packages_removed == []
        assert RecoveryResponse().aur_packages_failed == []


# ---------------------------------------------------------------------------
# Missing / unusable records
# ---------------------------------------------------------------------------


class TestUnavailableResponses:
    def test_returns_unavailable_when_no_record_exists(
        self, service: RecoveryService, record_dir: Path
    ):
        assert not record_dir.exists(), "the record directory must not exist yet"

        response = service.get_recovery_info("system-update")
        assert response.available is False
        assert response.reason is not None
        assert "system-update" in response.reason

    def test_returns_unavailable_for_an_unregistered_task(self, service: RecoveryService):
        response = service.get_recovery_info("not-a-task")
        assert response.available is False
        assert response.reason is not None
        assert "not-a-task" in response.reason

    def test_reports_a_malformed_record_instead_of_raising(
        self, service: RecoveryService, record_dir: Path
    ):
        record_dir.mkdir(parents=True, exist_ok=True)
        (record_dir / "system-update.json").write_text("{not json", encoding="utf-8")

        response = service.get_recovery_info("system-update")
        assert response.available is False
        assert response.reason is not None
        assert response.commands == ()

    def test_never_raises_when_the_record_is_not_a_file(
        self, service: RecoveryService, record_dir: Path
    ):
        """A directory where the record should be raises `IsADirectoryError`, not a domain error.

        Every unreadable-record shape must come back as `available=False`, because a stale or
        clobbered recovery file is an ordinary state the user is told about, not a bug.
        """
        (record_dir / "system-update.json").mkdir(parents=True)

        response = service.get_recovery_info("system-update")
        assert response.available is False
        assert response.reason

    @pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses file permissions")
    def test_never_raises_on_an_unreadable_record(self, service: RecoveryService, record_dir: Path):
        path = _write_record(record_dir)
        path.chmod(0o000)
        try:
            response = service.get_recovery_info("system-update")
        finally:
            path.chmod(0o600)

        assert response.available is False
        assert response.reason


# ---------------------------------------------------------------------------
# Reading the record
# ---------------------------------------------------------------------------


class TestReadsTheRecord:
    def test_reads_every_field_from_the_record(self, service: RecoveryService, record_dir: Path):
        _write_record(record_dir)

        response = service.get_recovery_info("system-update")
        assert response.available is True
        assert response.updated_at == "2026-09-29T18:00:00"
        assert response.snapshot_id == SNAPSHOT_ID
        assert response.sync_db_backup == str(record_dir / "sync-db/backup")
        assert response.manifest_before == str(record_dir / "manifests/before.txt")
        assert response.manifest_after == str(record_dir / "manifests/after.txt")
        assert response.packages_removed == ["linux-lts"]
        assert response.aur_packages_failed == ["yay"]

    def test_a_record_with_no_optional_artifacts_is_still_available(
        self, service: RecoveryService, record_dir: Path
    ):
        """A partial record (no snapper, no backup, nothing removed) is valid, just empty."""
        _write_record(
            record_dir,
            sync_db_backup=None,
            manifest_before=None,
            manifest_after=None,
            pre_update_snapshot_id=None,
            aur_packages_failed=[],
            packages_removed=[],
        )

        response = service.get_recovery_info("system-update")
        assert response.available is True
        assert response.reason is None
        assert response.snapshot_id is None
        assert response.sync_db_backup is None
        assert response.commands == ()

    def test_reading_never_creates_the_recovery_directory(
        self, service: RecoveryService, record_dir: Path
    ):
        """`recovery_dir` is created on demand by the writing task, never by this reader."""
        assert not record_dir.exists()

        service.get_recovery_info("system-update")
        assert not record_dir.exists()


# ---------------------------------------------------------------------------
# Command derivation
# ---------------------------------------------------------------------------


class TestCommandGating:
    def test_emits_no_snapshot_command_when_the_record_has_no_snapshot_id(
        self, service: RecoveryService, record_dir: Path
    ):
        """The gate that matters: a machine without snapper is never told to run snapper.

        `pre_update_snapshot_id` is `None` whenever snapshot tooling was unavailable or the
        pre-upgrade snapshot could not be queried, which is the normal case off-Btrfs.
        """
        _write_record(record_dir, pre_update_snapshot_id=None)

        response = service.get_recovery_info("system-update")
        assert not any("snapper" in command for command in response.commands)
        assert response.snapshot_id is None

    def test_a_non_integer_snapshot_id_is_not_used_as_a_command(
        self, service: RecoveryService, record_dir: Path
    ):
        """A string snapshot id would produce `snapper rollback none` if it were interpolated."""
        _write_record(record_dir, pre_update_snapshot_id="none")

        response = service.get_recovery_info("system-update")
        assert not any("snapper" in command for command in response.commands)
        assert response.snapshot_id == "none"

    def test_emits_no_sync_db_command_without_a_backup(
        self, service: RecoveryService, record_dir: Path
    ):
        _write_record(record_dir, sync_db_backup=None)

        response = service.get_recovery_info("system-update")
        assert not any("/var/lib/pacman/sync/" in command for command in response.commands)

    def test_emits_the_cache_command_only_when_packages_were_removed(
        self, service: RecoveryService, record_dir: Path
    ):
        _write_record(record_dir, packages_removed=[])

        response = service.get_recovery_info("system-update")
        assert CACHE_COMMAND not in response.commands


class TestCommandOrder:
    def test_a_record_with_every_field_present_yields_three_commands_in_order(
        self, service: RecoveryService, record_dir: Path
    ):
        """Order is part of the contract: most-relevant first, and the cheapest advice last."""
        _write_record(record_dir)

        response = service.get_recovery_info("system-update")
        assert len(response.commands) == EXPECTED_COMMAND_COUNT
        assert response.commands[0] == SNAPPER_COMMAND
        assert SCRIPT_PATH in response.commands[1]
        assert response.commands[1].startswith("bash ")
        assert response.commands[2] == CACHE_COMMAND

    def test_command_order_survives_a_record_missing_the_middle_command(
        self, service: RecoveryService, record_dir: Path
    ):
        _write_record(record_dir, sync_db_backup=None)

        response = service.get_recovery_info("system-update")
        assert response.commands == (
            SNAPPER_COMMAND,
            CACHE_COMMAND,
            *SINGLE_PACKAGE_INSTALLATION_COMMAND,
        )


# ---------------------------------------------------------------------------
# Restore script
# ---------------------------------------------------------------------------


class TestRestoreScript:
    def test_writes_a_restore_script_when_a_sync_backup_is_recorded(
        self, service: RecoveryService, record_dir: Path
    ):
        """No manifest is involved any more — the canonical method reads the restored sync DB."""
        _write_record(record_dir, manifest_before=None)

        response = service.get_recovery_info("system-update")

        assert any(SCRIPT_PATH in c for c in response.commands)
        script = record_dir / SCRIPT_PATH
        assert script.exists()
        assert "pacman -S -" in script.read_text(encoding="utf-8")

    def test_the_script_command_tells_the_user_to_read_it_first(
        self, service: RecoveryService, record_dir: Path
    ):
        _write_record(record_dir)

        response = service.get_recovery_info("system-update")

        command = next(c for c in response.commands if SCRIPT_PATH in c)
        assert command.startswith("bash ")
        assert "read it first" in command

    def test_no_script_when_the_record_has_no_sync_backup(
        self, service: RecoveryService, record_dir: Path
    ):
        """The script treats a missing backup as critical, so it is not generated without one."""
        _write_record(record_dir, sync_db_backup=None)

        response = service.get_recovery_info("system-update")

        assert not any(SCRIPT_PATH in c for c in response.commands)
        assert not (record_dir / SCRIPT_PATH).exists()

    def test_does_not_regenerate_an_existing_restore_script(
        self, service: RecoveryService, record_dir: Path
    ):
        """The user may have edited or partially run it — leave it alone on the second call."""
        _write_record(record_dir)
        script = record_dir / SCRIPT_PATH
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("USER EDITED THIS", encoding="utf-8")

        service.get_recovery_info("system-update")

        assert script.read_text(encoding="utf-8") == "USER EDITED THIS"

    def test_the_script_is_executable(self, service: RecoveryService, record_dir: Path):
        """The suggested command runs it with `bash`, but the 0o755 bit costs nothing."""
        _write_record(record_dir)

        service.get_recovery_info("system-update")

        assert oct((record_dir / SCRIPT_PATH).stat().st_mode) == "0o100755"

    def test_the_cache_pointer_is_kept_alongside_the_script(
        self, service: RecoveryService, record_dir: Path
    ):
        """The script cannot restore a package this run REMOVED — the cache pointer still covers it.

        `pacman -Qe`/`-Qmq` enumerate the installed set, so a removed package is in neither.
        Dropping this command would leave that case with no guidance at all, and would make
        `cache_keep_uninstalled_versions` (default 1) pointless.
        """
        _write_record(record_dir, packages_removed=["linux"])

        response = service.get_recovery_info("system-update")

        assert CACHE_COMMAND in response.commands
        assert any(SCRIPT_PATH in c for c in response.commands)

    def test_writing_the_script_does_not_disturb_the_packages_removed_display_path(
        self, service: RecoveryService, record_dir: Path
    ):
        """`packages_removed` is presentation data, not a script input, so it must survive."""
        _write_record(record_dir, packages_removed=["linux-lts"])

        response = service.get_recovery_info("system-update")

        assert response.packages_removed == ["linux-lts"]
