"""Unit tests for TaskScheduler."""

from datetime import datetime, timedelta

import pytest

from archcare.config import AppState, TasksConfig, TaskStatus
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
    def test_raises_for_unknown_task(
        self, tasks_config: TasksConfig, fresh_state: AppState
    ):
        scheduler = _scheduler(tasks_config, fresh_state)
        with pytest.raises(ValueError, match="Task not found") as exc_info:
            scheduler.get_schedule_info("does-not-exist")
        assert "does-not-exist" in str(exc_info.value)

    def test_never_run_task_is_due(
        self, tasks_config: TasksConfig, fresh_state: AppState
    ):
        info = _scheduler(tasks_config, fresh_state).get_schedule_info(
            "test-manual-task"
        )
        assert info.is_due is True

    def test_never_run_task_has_no_last_run(
        self, tasks_config: TasksConfig, fresh_state: AppState
    ):
        info = _scheduler(tasks_config, fresh_state).get_schedule_info(
            "test-manual-task"
        )
        assert info.last_run is None

    def test_never_run_task_reason_mentions_never(
        self, tasks_config: TasksConfig, fresh_state: AppState
    ):
        info = _scheduler(tasks_config, fresh_state).get_schedule_info(
            "test-manual-task"
        )
        assert "never" in info.reason.lower()

    def test_future_next_due_task_is_not_due(
        self, tasks_config: TasksConfig, state_with_recent_run: AppState
    ):
        info = _scheduler(tasks_config, state_with_recent_run).get_schedule_info(
            "test-auto-task"
        )
        assert info.is_due is False

    def test_past_next_due_task_is_due(
        self, tasks_config: TasksConfig, state_with_overdue_run: AppState
    ):
        info = _scheduler(tasks_config, state_with_overdue_run).get_schedule_info(
            "test-auto-task"
        )
        assert info.is_due is True

    def test_overdue_task_has_positive_days_overdue(
        self, tasks_config: TasksConfig, state_with_overdue_run: AppState
    ):
        info = _scheduler(tasks_config, state_with_overdue_run).get_schedule_info(
            "test-auto-task"
        )
        assert info.days_overdue > 0

    def test_not_due_task_has_zero_days_overdue(
        self, tasks_config: TasksConfig, state_with_recent_run: AppState
    ):
        info = _scheduler(tasks_config, state_with_recent_run).get_schedule_info(
            "test-auto-task"
        )
        assert info.days_overdue == 0


# ---------------------------------------------------------------------------
# get_due_tasks
# ---------------------------------------------------------------------------


class TestGetDueTasks:
    def test_all_tasks_due_when_never_run(
        self, tasks_config: TasksConfig, fresh_state: AppState
    ):
        due = _scheduler(tasks_config, fresh_state).get_due_tasks()
        assert len(due) == len(tasks_config.get_enabled_tasks())

    def test_excludes_task_with_future_next_due(
        self, tasks_config: TasksConfig, state_with_recent_run: AppState
    ):
        due = _scheduler(tasks_config, state_with_recent_run).get_due_tasks()
        due_names = {info.task_name for info in due}
        assert "test-auto-task" not in due_names

    def test_includes_overdue_task(
        self, tasks_config: TasksConfig, state_with_overdue_run: AppState
    ):
        due = _scheduler(tasks_config, state_with_overdue_run).get_due_tasks()
        due_names = {info.task_name for info in due}
        assert "test-auto-task" in due_names

    def test_all_returned_tasks_are_due(
        self, tasks_config: TasksConfig, fresh_state: AppState
    ):
        due = _scheduler(tasks_config, fresh_state).get_due_tasks()
        assert all(info.is_due for info in due)

    def test_sorted_most_overdue_first(self, tasks_config: TasksConfig):
        """Most overdue task should appear before a task that is just due."""
        state = AppState()
        # test-manual-task overdue by 10 days
        state.update_task_state(
            task_name="test-manual-task",
            status=TaskStatus.SUCCESS,
            next_due=datetime.now() - timedelta(days=10),
            error=None,
            skip_reason=None,
            skip_message=None,
        )
        # test-auto-task overdue by 1 day
        state.update_task_state(
            task_name="test-auto-task",
            status=TaskStatus.SUCCESS,
            next_due=datetime.now() - timedelta(days=1),
            error=None,
            skip_reason=None,
            skip_message=None,
        )
        due = _scheduler(tasks_config, state).get_due_tasks()
        assert due[0].task_name == "test-manual-task"
        assert due[1].task_name == "test-auto-task"


# ---------------------------------------------------------------------------
# get_maintenance_summary
# ---------------------------------------------------------------------------


class TestGetMaintenanceSummary:
    def test_total_equals_enabled_task_count(
        self, tasks_config: TasksConfig, fresh_state: AppState
    ):
        summary = _scheduler(tasks_config, fresh_state).get_maintenance_summary()
        assert summary["total"] == len(tasks_config.get_enabled_tasks())

    def test_all_due_when_never_run(
        self, tasks_config: TasksConfig, fresh_state: AppState
    ):
        summary = _scheduler(tasks_config, fresh_state).get_maintenance_summary()
        assert summary["due"] == len(tasks_config.get_enabled_tasks())

    def test_zero_due_when_all_tasks_have_future_next_due(
        self, tasks_config: TasksConfig
    ):
        state = AppState()
        for name in tasks_config.get_enabled_tasks():
            state.update_task_state(
                task_name=name,
                status=TaskStatus.SUCCESS,
                next_due=datetime.now() + timedelta(days=14),
                error=None,
                skip_reason=None,
                skip_message=None,
            )
        summary = _scheduler(tasks_config, state).get_maintenance_summary()
        assert summary["due"] == 0

    def test_overdue_count_excludes_just_due_tasks(self, tasks_config: TasksConfig):
        """A task due today (days_overdue == 0) is due but not overdue."""
        state = AppState()
        state.update_task_state(
            task_name="test-manual-task",
            status=TaskStatus.SUCCESS,
            next_due=datetime.now() - timedelta(hours=1),  # due, overdue by 0 days
            error=None,
            skip_reason=None,
            skip_message=None,
        )
        summary = _scheduler(tasks_config, state).get_maintenance_summary()
        assert summary["due"] >= 1
        assert summary["overdue"] == 0

    def test_summary_has_required_keys(
        self, tasks_config: TasksConfig, fresh_state: AppState
    ):
        summary = _scheduler(tasks_config, fresh_state).get_maintenance_summary()
        assert {"total", "due", "overdue", "upcoming"} <= summary.keys()
