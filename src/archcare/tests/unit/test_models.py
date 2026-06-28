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
# AppState
# ---------------------------------------------------------------------------


class TestAppState:
    def test_get_task_state_creates_new_state_for_unknown_task(self, fresh_state):
        state = fresh_state.get_task_state("brand-new")
        assert state.last_run is None
        assert state.run_count == 0

    def test_get_task_state_returns_same_object_each_time(self, fresh_state):
        first = fresh_state.get_task_state("some-task")
        second = fresh_state.get_task_state("some-task")
        assert first is second

    def test_update_sets_last_run_to_now(self, fresh_state):
        before = datetime.now()
        _update(fresh_state, "task-a", TaskStatus.SUCCESS)
        assert fresh_state.get_task_state("task-a").last_run >= before

    def test_update_records_status(self, fresh_state):
        _update(fresh_state, "task-a", TaskStatus.FAILURE)
        assert fresh_state.get_task_state("task-a").last_status == TaskStatus.FAILURE

    def test_run_count_increments_on_each_update(self, fresh_state):
        for _ in range(3):
            _update(fresh_state, "task-a", TaskStatus.SUCCESS)
        assert fresh_state.get_task_state("task-a").run_count == 3

    def test_update_stores_next_due(self, fresh_state):
        due = datetime.now() + timedelta(days=7)
        _update(fresh_state, "task-a", TaskStatus.SUCCESS, next_due=due)
        assert fresh_state.get_task_state("task-a").next_due == due

    def test_update_stores_error_message(self, fresh_state):
        _update(fresh_state, "task-a", TaskStatus.FAILURE, error="timeout")
        assert fresh_state.get_task_state("task-a").last_error == "timeout"

    def test_update_stores_skip_reason(self, fresh_state):
        _update(
            fresh_state,
            "task-a",
            TaskStatus.SKIPPED,
            skip_reason=SkipReason.NOT_DUE,
        )
        assert fresh_state.get_task_state("task-a").skip_reason == SkipReason.NOT_DUE

    def test_independent_tasks_have_independent_state(self, fresh_state):
        _update(fresh_state, "task-a", TaskStatus.SUCCESS)
        _update(fresh_state, "task-b", TaskStatus.FAILURE)
        assert fresh_state.get_task_state("task-a").last_status == TaskStatus.SUCCESS
        assert fresh_state.get_task_state("task-b").last_status == TaskStatus.FAILURE


# ---------------------------------------------------------------------------
# MirrorlistSettings validators
# ---------------------------------------------------------------------------


class TestMirrorlistSettings:
    @pytest.mark.parametrize("protocol", ["http", "https", "rsync"])
    def test_valid_protocol_accepted(self, protocol):
        assert MirrorlistSettings(protocol=protocol).protocol == protocol

    def test_invalid_protocol_raises(self):
        with pytest.raises(ValidationError):
            MirrorlistSettings(protocol="ftp")

    @pytest.mark.parametrize("sort", ["age", "rate", "country", "score", "delay"])
    def test_valid_sort_accepted(self, sort):
        assert MirrorlistSettings(sort=sort).sort == sort

    def test_invalid_sort_raises(self):
        with pytest.raises(ValidationError):
            MirrorlistSettings(sort="random")


# ---------------------------------------------------------------------------
# MaintenanceCheckSettings validators
# ---------------------------------------------------------------------------


class TestMaintenanceCheckSettings:
    @pytest.mark.parametrize("mode", ["terminal", "file", "both"])
    def test_valid_output_mode_accepted(self, mode):
        assert MaintenanceCheckSettings(output_mode=mode).output_mode == mode

    def test_invalid_output_mode_raises(self):
        with pytest.raises(ValidationError):
            MaintenanceCheckSettings(output_mode="stdout")

    @pytest.mark.parametrize("level", ["critical", "warning", "info"])
    def test_valid_notification_level_accepted(self, level):
        assert (
            MaintenanceCheckSettings(notification_level=level).notification_level
            == level
        )

    def test_invalid_notification_level_raises(self):
        with pytest.raises(ValidationError):
            MaintenanceCheckSettings(notification_level="debug")


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
