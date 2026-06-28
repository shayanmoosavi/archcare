"""Unit tests for config/models.py."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from archcare.config import AppSettings, AppState, SkipReason, TasksConfig, TaskStatus
from archcare.config.models import MaintenanceCheckSettings, MirrorlistSettings

# ---------------------------------------------------------------------------
# TaskConfig
# ---------------------------------------------------------------------------


class TestTaskConfig:
    def test_valid_config_is_accepted(self, automated_task):
        assert automated_task.name == "test-auto-task"
        assert automated_task.enabled is True
        assert automated_task.frequency == 7

    def test_name_with_spaces_raises(self):
        with pytest.raises(ValidationError):
            _make_task(name="task with spaces")

    def test_command_with_spaces_raises(self):
        with pytest.raises(ValidationError):
            _make_task(command="has spaces")

    def test_zero_frequency_raises(self):
        with pytest.raises(ValidationError):
            _make_task(frequency=0)

    def test_negative_frequency_raises(self):
        with pytest.raises(ValidationError):
            _make_task(frequency=-1)

    def test_hyphens_and_underscores_allowed_in_name(self):
        task = _make_task(name="my_task-name")
        assert task.name == "my_task-name"


# ---------------------------------------------------------------------------
# TasksConfig
# ---------------------------------------------------------------------------


class TestTasksConfig:
    def test_get_task_returns_matching_config(self, tasks_config, automated_task):
        result = tasks_config.get_task(automated_task.name)
        assert result == automated_task

    def test_get_task_raises_for_unknown_name(self, tasks_config):
        with pytest.raises(ValueError):
            tasks_config.get_task("does-not-exist")

    def test_get_enabled_tasks_excludes_disabled(self, automated_task, disabled_task):
        config = TasksConfig(
            tasks={
                automated_task.name: automated_task,
                disabled_task.name: disabled_task,
            }
        )
        enabled = config.get_enabled_tasks()
        assert automated_task.name in enabled
        assert disabled_task.name not in enabled

    def test_get_enabled_tasks_includes_all_when_all_enabled(self, tasks_config):
        assert len(tasks_config.get_enabled_tasks()) == len(tasks_config.tasks)

    def test_get_tasks_by_type_returns_automated(
        self, tasks_config, automated_task, manual_task
    ):
        result = tasks_config.get_tasks_by_type("automated")
        assert automated_task.name in result
        assert manual_task.name not in result

    def test_get_tasks_by_type_returns_manual(
        self, tasks_config, automated_task, manual_task
    ):
        result = tasks_config.get_tasks_by_type("manual")
        assert manual_task.name in result
        assert automated_task.name not in result

    def test_get_tasks_by_type_raises_for_invalid_type(self, tasks_config):
        with pytest.raises(ValueError):
            tasks_config.get_tasks_by_type("weekly")

    def test_empty_config_has_no_enabled_tasks(self, empty_tasks_config):
        assert empty_tasks_config.get_enabled_tasks() == {}


# ---------------------------------------------------------------------------
# AppSettings — path computation
# ---------------------------------------------------------------------------


class TestAppSettingsPaths:
    def test_home_dir_is_path_home_when_user_is_none(self, monkeypatch):
        monkeypatch.delenv("SUDO_USER", raising=False)
        settings = AppSettings(user=None)
        assert settings.home_dir == Path.home()

    def test_home_dir_uses_user_name(self, monkeypatch):
        monkeypatch.delenv("SUDO_USER", raising=False)
        settings = AppSettings(user="alice")
        assert settings.home_dir == Path("/home/alice")

    def test_sudo_user_overrides_user(self, monkeypatch):
        monkeypatch.setenv("SUDO_USER", "bob")
        settings = AppSettings(user="alice")
        assert settings.home_dir == Path("/home/bob")

    def test_log_dir_is_under_home(self, monkeypatch):
        monkeypatch.delenv("SUDO_USER", raising=False)
        s = AppSettings(user="alice")
        assert s.log_dir == Path("/home/alice/.local/state/archcare/logs")

    def test_config_dir_is_under_home(self, monkeypatch):
        monkeypatch.delenv("SUDO_USER", raising=False)
        s = AppSettings(user="alice")
        assert s.config_dir == Path("/home/alice/.config/archcare")

    def test_state_file_is_under_home(self, monkeypatch):
        monkeypatch.delenv("SUDO_USER", raising=False)
        s = AppSettings(user="alice")
        assert s.state_file == Path("/home/alice/.local/state/archcare/state.json")

    def test_report_dir_is_under_home(self, monkeypatch):
        monkeypatch.delenv("SUDO_USER", raising=False)
        s = AppSettings(user="alice")
        assert s.report_dir == Path("/home/alice/.local/state/archcare/reports")


class TestAppSettingsEnsureDirectories:
    def test_all_required_directories_are_created(self, tmp_path, monkeypatch):
        """
        Redirect Path.home() to tmp_path so ensure_directories() writes to a
        temp location instead of the real home directory.
        """
        monkeypatch.delenv("SUDO_USER", raising=False)
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
        settings = AppSettings(user=None)

        settings.ensure_directories()

        assert settings.log_dir.exists()
        assert settings.config_dir.exists()
        assert settings.state_file.parent.exists()
        assert settings.report_dir.exists()

    def test_ensure_directories_is_idempotent(self, tmp_path, monkeypatch):
        """Calling twice must not raise even if directories already exist."""
        monkeypatch.delenv("SUDO_USER", raising=False)
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
        settings = AppSettings(user=None)

        settings.ensure_directories()
        settings.ensure_directories()  # must not raise


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _make_task(**overrides):
    """Build a minimal TaskConfig, merging any overrides."""
    from archcare.config import TaskConfig

    defaults = {
        "name": "test-task",
        "type": "automated",
        "frequency": 7,
        "description": "A test task",
        "command": "test-task",
        "enabled": True,
    }
    return TaskConfig.model_validate({**defaults, **overrides})


def _update(
    state: AppState,
    task_name: str,
    status: TaskStatus,
    next_due=None,
    error=None,
    skip_reason=None,
    skip_message=None,
) -> None:
    """Thin wrapper so test bodies stay single-line."""
    state.update_task_state(
        task_name=task_name,
        status=status,
        next_due=next_due,
        error=error,
        skip_reason=skip_reason,
        skip_message=skip_message,
    )
