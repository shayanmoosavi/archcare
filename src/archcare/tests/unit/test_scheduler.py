"""Unit tests for TaskScheduler."""

from datetime import datetime, timedelta

import pytest

from archcare.config import AppState, TasksConfig
from archcare.core import TaskScheduler

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scheduler(tasks_config: TasksConfig, state: AppState) -> TaskScheduler:
    return TaskScheduler(tasks_config, state)


# ---------------------------------------------------------------------------
# get_schedule_info — single task
# ---------------------------------------------------------------------------


class TestGetScheduleInfo:
    def test_raises_for_unknown_task(self, tasks_config, fresh_state):
        scheduler = _scheduler(tasks_config, fresh_state)
        with pytest.raises(ValueError, match="Task not found") as exc_info:
            scheduler.get_schedule_info("does-not-exist")
        assert "does-not-exist" in str(exc_info.value)

    def test_never_run_task_is_due(self, tasks_config, fresh_state):
        info = _scheduler(tasks_config, fresh_state).get_schedule_info(
            "test-manual-task"
        )
        assert info.is_due is True

    def test_never_run_task_has_no_last_run(self, tasks_config, fresh_state):
        info = _scheduler(tasks_config, fresh_state).get_schedule_info(
            "test-manual-task"
        )
        assert info.last_run is None

    def test_never_run_task_reason_mentions_never(self, tasks_config, fresh_state):
        info = _scheduler(tasks_config, fresh_state).get_schedule_info(
            "test-manual-task"
        )
        assert "never" in info.reason.lower()

    def test_future_next_due_task_is_not_due(self, tasks_config, state_with_recent_run):
        info = _scheduler(tasks_config, state_with_recent_run).get_schedule_info(
            "test-auto-task"
        )
        assert info.is_due is False

    def test_past_next_due_task_is_due(self, tasks_config, state_with_overdue_run):
        info = _scheduler(tasks_config, state_with_overdue_run).get_schedule_info(
            "test-auto-task"
        )
        assert info.is_due is True

    def test_overdue_task_has_positive_days_overdue(
        self, tasks_config, state_with_overdue_run
    ):
        info = _scheduler(tasks_config, state_with_overdue_run).get_schedule_info(
            "test-auto-task"
        )
        assert info.days_overdue > 0

    def test_not_due_task_has_zero_days_overdue(
        self, tasks_config, state_with_recent_run
    ):
        info = _scheduler(tasks_config, state_with_recent_run).get_schedule_info(
            "test-auto-task"
        )
        assert info.days_overdue == 0
