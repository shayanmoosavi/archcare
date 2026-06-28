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
