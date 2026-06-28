"""Unit tests for ConfigService and TimerService."""

from operator import call
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from archcare.services.setup_service import ConfigService, TimerService

_PATCH_CREATE_CONFIG = "archcare.services.setup_service.create_default_config_files"
_PATCH_SYSTEMCTL = "archcare.services.setup_service.run_systemctl"


# ---------------------------------------------------------------------------
# Helpers and fixtures
# ---------------------------------------------------------------------------


def _systemctl_result(success: bool, stdout: str = "") -> MagicMock:
    result = MagicMock()
    result.success = success
    result.stdout = stdout
    return result


@pytest.fixture
def timer_service(tmp_path, mock_executor, monkeypatch) -> TimerService:
    """
    TimerService with SYSTEMD_DIR redirected to tmp_path.

    Patching the class attribute before construction is essential because
    __init__ derives service_file and timer_file from SYSTEMD_DIR at that
    point — patching after construction would leave the paths pointing at
    the real /etc/systemd/system.
    """
    monkeypatch.setattr(TimerService, "SYSTEMD_DIR", tmp_path)
    return TimerService(mock_executor, user="alice", home_dir=str(tmp_path / "home"))


# ---------------------------------------------------------------------------
# ConfigService
# ---------------------------------------------------------------------------


class TestConfigService:
    def test_default_config_dir_is_under_home(self):
        service = ConfigService()
        assert service.config_dir == Path.home() / ".config/archcare"

    def test_custom_config_dir_is_accepted(self, tmp_path):
        service = ConfigService(config_dir=tmp_path)
        assert service.config_dir == tmp_path

    def test_check_existing_returns_empty_when_dir_absent(self, tmp_path):
        service = ConfigService(config_dir=tmp_path / "nonexistent")
        assert service.check_existing() == []

    def test_check_existing_returns_empty_when_dir_has_no_toml(self, tmp_path):
        config_dir = tmp_path / "archcare"
        config_dir.mkdir()
        (config_dir / "readme.txt").touch()
        service = ConfigService(config_dir=config_dir)
        assert service.check_existing() == []

    def test_check_existing_finds_toml_files(self, tmp_path):
        config_dir = tmp_path / "archcare"
        config_dir.mkdir()
        (config_dir / "settings.toml").touch()
        (config_dir / "tasks.toml").touch()
        service = ConfigService(config_dir=config_dir)
        found = service.check_existing()
        assert len(found) == 2

    def test_check_existing_excludes_non_toml_files(self, tmp_path):
        config_dir = tmp_path / "archcare"
        config_dir.mkdir()
        (config_dir / "settings.toml").touch()
        (config_dir / "readme.txt").touch()
        service = ConfigService(config_dir=config_dir)
        found = service.check_existing()
        assert all(f.suffix == ".toml" for f in found)

    def test_initialize_returns_response_with_correct_config_dir(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(_PATCH_CREATE_CONFIG, lambda *a, **kw: None)
        result = ConfigService(config_dir=tmp_path).initialize()
        assert result.config_dir == tmp_path

    def test_initialize_calls_create_with_correct_dir(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(
            _PATCH_CREATE_CONFIG,
            lambda config_dir, **kw: calls.append(config_dir),
        )
        ConfigService(config_dir=tmp_path).initialize()
        assert calls[0] == tmp_path

    def test_initialize_always_passes_force_true(self, tmp_path, monkeypatch):
        """initialize() must overwrite existing files unconditionally."""
        calls = []
        monkeypatch.setattr(
            _PATCH_CREATE_CONFIG,
            lambda config_dir, force=False: calls.append(force),
        )
        ConfigService(config_dir=tmp_path).initialize()
        assert calls[0] is True


# ---------------------------------------------------------------------------
# TimerService.get_automated_tasks
# ---------------------------------------------------------------------------


class TestGetAutomatedTasks:
    def test_returns_only_automated_tasks(self, timer_service):
        result = timer_service.get_automated_tasks()
        assert all(str(t.task_type) == "automated" for t in result.values())

    def test_automated_task_present(self, timer_service, automated_task):
        result = timer_service.get_automated_tasks()
        assert automated_task.name in result

    def test_manual_task_excluded(self, timer_service, manual_task):
        result = timer_service.get_automated_tasks()
        assert manual_task.name not in result


# ---------------------------------------------------------------------------
# TimerService.install_templates
# ---------------------------------------------------------------------------


class TestInstallTemplates:
    def test_dry_run_does_not_write_files(self, timer_service):
        timer_service.install_templates(dry_run=True)
        assert not timer_service.timer_file.exists()
        assert not timer_service.service_file.exists()

    def test_dry_run_response_carries_flag(self, timer_service):
        response = timer_service.install_templates(dry_run=True)
        assert response.dry_run is True

    def test_non_dry_run_writes_files(self, timer_service):
        timer_service.install_templates(dry_run=False)
        assert timer_service.timer_file.exists()
        assert timer_service.service_file.exists()

    def test_service_file_contains_target_user(self, timer_service):
        timer_service.install_templates(dry_run=False)
        assert "alice" in timer_service.service_file.read_text()

    def test_service_file_uses_correct_exec_start(self, timer_service):
        """
        Regression: ExecStart must have the correct command signature
        (e.g., 'archcare task run'), because it's easy to forget to update the
        service file content after refactoring CLI.
        """
        timer_service.install_templates(dry_run=False)
        assert "archcare task run" in timer_service.service_file.read_text()

    def test_response_carries_service_file_path(self, timer_service):
        response = timer_service.install_templates(dry_run=False)
        assert response.service_file == timer_service.service_file

    def test_response_carries_timer_file_path(self, timer_service):
        response = timer_service.install_templates(dry_run=False)
        assert response.timer_file == timer_service.timer_file


class TestReload:
    def test_dry_run_does_not_call_systemctl(self, timer_service, monkeypatch):
        calls = []
        monkeypatch.setattr(_PATCH_SYSTEMCTL, lambda *a: calls.append(a))
        timer_service.reload(dry_run=True)
        assert not calls

    def test_dry_run_returns_success(self, timer_service, monkeypatch):
        monkeypatch.setattr(_PATCH_SYSTEMCTL, lambda *_: _systemctl_result(True))
        response = timer_service.reload(dry_run=True)
        assert response.success is True

    def test_successful_daemon_reload_returns_success(self, timer_service, monkeypatch):
        monkeypatch.setattr(_PATCH_SYSTEMCTL, lambda *_: _systemctl_result(True))
        response = timer_service.reload(dry_run=False)
        assert response.success is True

    def test_failed_daemon_reload_returns_failure(self, timer_service, monkeypatch):
        """SystemdReloadError is caught internally; success=False is returned."""
        monkeypatch.setattr(_PATCH_SYSTEMCTL, lambda *_: _systemctl_result(False))
        response = timer_service.reload(dry_run=False)
        assert response.success is False


# ---------------------------------------------------------------------------
# TimerService.setup_timers
# ---------------------------------------------------------------------------


class TestSetupTimers:
    def test_dry_run_makes_no_systemctl_calls(
        self, timer_service, automated_task, monkeypatch
    ):
        calls = []
        monkeypatch.setattr(_PATCH_SYSTEMCTL, lambda *a: calls.append(a))
        timer_service.setup_timers(
            {automated_task.name: automated_task}, dry_run=True, enable=True
        )
        assert not calls

    def test_enable_false_makes_no_systemctl_calls(
        self, timer_service, automated_task, monkeypatch
    ):
        calls = []
        monkeypatch.setattr(_PATCH_SYSTEMCTL, lambda *a: calls.append(a))
        timer_service.setup_timers(
            {automated_task.name: automated_task}, dry_run=False, enable=False
        )
        assert not calls

    def test_skipped_run_has_empty_enabled_timers(self, timer_service, automated_task):
        response = timer_service.setup_timers(
            {automated_task.name: automated_task}, dry_run=True, enable=True
        )
        assert not response.enabled_timers

    def test_skipped_run_has_no_timer_status(self, timer_service, automated_task):
        response = timer_service.setup_timers(
            {automated_task.name: automated_task}, dry_run=True, enable=True
        )
        assert response.timer_status is None

    def test_enabled_response_has_one_entry_per_task(
        self, timer_service, automated_task, monkeypatch
    ):
        monkeypatch.setattr(_PATCH_SYSTEMCTL, lambda *_: _systemctl_result(True, ""))
        response = timer_service.setup_timers(
            {automated_task.name: automated_task}, dry_run=False, enable=True
        )
        assert len(response.enabled_timers) == 1

    def test_timer_name_follows_archcare_convention(
        self, timer_service, automated_task, monkeypatch
    ):
        monkeypatch.setattr(_PATCH_SYSTEMCTL, lambda *_: _systemctl_result(True, ""))
        response = timer_service.setup_timers(
            {automated_task.name: automated_task}, dry_run=False, enable=True
        )
        expected = f"archcare@{automated_task.name}.timer"
        assert response.enabled_timers[0].timer_name == expected

    def test_successful_enable_marked_in_response(
        self, timer_service, automated_task, monkeypatch
    ):
        monkeypatch.setattr(_PATCH_SYSTEMCTL, lambda *_: _systemctl_result(True, ""))
        response = timer_service.setup_timers(
            {automated_task.name: automated_task}, dry_run=False, enable=True
        )
        assert response.enabled_timers[0].enabled is True

    def test_failed_enable_marked_in_response(
        self, timer_service, automated_task, monkeypatch
    ):
        monkeypatch.setattr(_PATCH_SYSTEMCTL, lambda *_: _systemctl_result(False))
        response = timer_service.setup_timers(
            {automated_task.name: automated_task}, dry_run=False, enable=True
        )
        assert response.enabled_timers[0].enabled is False

    def test_timer_status_populated_from_list_timers_output(
        self, timer_service, automated_task, monkeypatch
    ):
        """The last run_systemctl call (list-timers) provides timer_status."""
        monkeypatch.setattr(
            _PATCH_SYSTEMCTL,
            lambda *_: _systemctl_result(True, f"archcare@{automated_task.name}.timer"),
        )
        response = timer_service.setup_timers(
            {automated_task.name: automated_task}, dry_run=False, enable=True
        )
        assert response.timer_status == f"archcare@{automated_task.name}.timer"

    def test_response_carries_automated_tasks(
        self, timer_service, automated_task, monkeypatch
    ):
        monkeypatch.setattr(_PATCH_SYSTEMCTL, lambda *_: _systemctl_result(True, ""))
        tasks = {automated_task.name: automated_task}
        response = timer_service.setup_timers(tasks, dry_run=False, enable=True)
        assert response.automated_tasks == tasks
