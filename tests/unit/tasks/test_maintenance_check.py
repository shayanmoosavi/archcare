"""
Unit tests for MaintenanceCheckTask (tasks/maintenance_check.py).

Scope: the categorization/scheduling logic that's genuinely this task's
own - execute()'s orchestration, _check_task()'s branching, and the static
helper methods. post_execute()/_send_notification()/_save_report()/
_cleanup_old_reports() are a separate, natural follow-up pass.

"""

from datetime import datetime, timedelta

import pytest

from archcare.config import AppSettings, AppState, TaskConfig, TasksConfig, TaskStatus
from archcare.config.models import MaintenanceCheckSettings
from archcare.core.models import IssueSeverity, MaintenanceCheckResult, MaintenanceIssue
from archcare.core.scheduler import TaskScheduleInfo, TaskScheduler
from archcare.tasks.maintenance_check import MaintenanceCheckTask

_MODULE = "archcare.tasks.maintenance_check"
_PATCH_CONFIG_LOADER = f"{_MODULE}.ConfigLoader"

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _schedule_info(
    task_name: str,
    is_due: bool,
    next_due: datetime | None = None,
    last_run: datetime | None = None,
    days_overdue: int = 0,
    reason: str = "",
) -> TaskScheduleInfo:
    return TaskScheduleInfo(
        task_name=task_name,
        is_due=is_due,
        next_due=next_due,
        last_run=last_run,
        days_overdue=days_overdue,
        reason=reason,
    )


def _task_config(
    name: str, command: str, task_type: str, frequency: int = 7
) -> TaskConfig:
    return TaskConfig.model_validate(
        {
            "name": name,
            "type": task_type,
            "frequency": frequency,
            "description": "A test task",
            "command": command,
            "enabled": True,
        }
    )


@pytest.fixture
def maintenance_config() -> TaskConfig:
    return _task_config("maintenance-check", "check-maintenance", "automated", 1)


@pytest.fixture
def settings() -> AppSettings:
    return AppSettings()


@pytest.fixture
def task(maintenance_config, settings, mocker) -> MaintenanceCheckTask:
    """
    A minimal task instance - sufficient for the helper-method tests below,
    none of which read self.state/self.tasks_config/self.scheduler.
    """
    mocker.patch(_PATCH_CONFIG_LOADER)
    return MaintenanceCheckTask(maintenance_config, settings)


@pytest.fixture
def task_with_thresholds(maintenance_config, mocker) -> MaintenanceCheckTask:
    """
    Custom, non-default thresholds - the real defaults (critical=7,
    warning=0) make it impossible to ever reach the INFO/WARNING branches
    of _determine_severity for any days_overdue >= 1, since warning=0
    already catches everything.
    """
    mocker.patch(_PATCH_CONFIG_LOADER)
    custom_settings = AppSettings(
        maintenance_check=MaintenanceCheckSettings(
            critical_threshold_days=10, warning_threshold_days=5
        )
    )
    return MaintenanceCheckTask(maintenance_config, custom_settings)


@pytest.fixture
def make_task(maintenance_config, settings, mocker):
    """Builds a task and swaps in real tasks_config/state/scheduler."""

    def _make(
        tasks_config: TasksConfig | None = None, state: AppState | None = None
    ) -> MaintenanceCheckTask:
        mocker.patch(_PATCH_CONFIG_LOADER)
        built = MaintenanceCheckTask(maintenance_config, settings)
        built.tasks_config = tasks_config or TasksConfig(tasks={})
        built.state = state or AppState()
        built.scheduler = TaskScheduler(built.tasks_config, built.state)
        return built

    return _make


# ---------------------------------------------------------------------------
# _format_time_ago
# ---------------------------------------------------------------------------


class TestFormatTimeAgo:
    @pytest.mark.parametrize(
        "time_ago,expected",
        [
            (None, "never"),
            (datetime.now() - timedelta(seconds=1), "just now"),
            (datetime.now() - timedelta(minutes=1, seconds=1), "1 minute ago"),
            (datetime.now() - timedelta(hours=1, minutes=1), "1 hour ago"),
            (datetime.now() - timedelta(hours=5, minutes=1, seconds=1), "5 hours ago"),
            (datetime.now() - timedelta(days=1, hours=1), "1 day ago"),
            (
                datetime.now() - timedelta(days=5, hours=1, minutes=1, seconds=1),
                "5 days ago",
            ),
        ],
    )
    def test_time_ago_formats_correctly(self, time_ago, expected):
        assert MaintenanceCheckTask._format_time_ago(time_ago) == expected


# ---------------------------------------------------------------------------
# _format_overdue_description
# ---------------------------------------------------------------------------


class TestFormatOverdueDescription:
    def test_none_raises_value_error(self, automated_task):
        with pytest.raises(ValueError):
            MaintenanceCheckTask._format_overdue_description(automated_task, None)

    def test_zero_days_is_due_today(self, automated_task):
        """
        Regression test for the fix: previously unreachable, since the
        outer truthy check excluded 0 before this branch could run,
        silently returning None instead.
        """
        result = MaintenanceCheckTask._format_overdue_description(automated_task, 0)
        assert result == f"Task `{automated_task.name}` is due today"

    def test_one_day_singular(self, automated_task):
        result = MaintenanceCheckTask._format_overdue_description(automated_task, 1)
        assert result == f"Task `{automated_task.name}` is overdue by 1 day"

    def test_multiple_days_plural(self, automated_task):
        result = MaintenanceCheckTask._format_overdue_description(automated_task, 5)
        assert result == f"Task `{automated_task.name}` is overdue by 5 days"
