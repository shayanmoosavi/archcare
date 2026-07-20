"""
Unit tests for MaintenanceCheckTask (tasks/maintenance_check.py).

Scope: the categorization/scheduling logic that's genuinely this task's
own - execute()'s orchestration, _check_task()'s branching, and the static
helper methods. post_execute()/_send_notification()/_save_report()/
_cleanup_old_reports() are a separate, natural follow-up pass.

"""

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock

import pytest

from archcare.config import AppSettings, AppState, TaskConfig, TasksConfig, TaskStatus
from archcare.config.models import MaintenanceCheckSettings
from archcare.core import (
    IssueSeverity,
    MaintenanceCheckResult,
    MaintenanceIssue,
    TaskResult,
    TaskScheduleInfo,
    TaskScheduler,
)
from archcare.tasks.maintenance_check import MaintenanceCheckTask
from archcare.utils.notifications import NotificationManager

_MODULE = "archcare.tasks.maintenance_check"
_PATCH_CONFIG_LOADER = f"{_MODULE}.ConfigLoader"


type MaintenanceCheckTaskFactory = Callable[..., MaintenanceCheckTask]

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


def _task_config(name: str, task_type: str, frequency: int = 7) -> TaskConfig:
    return TaskConfig.model_validate(
        {
            "name": name,
            "type": task_type,
            "frequency": frequency,
            "description": "A test task",
            "enabled": True,
        }
    )


@pytest.fixture
def maintenance_config() -> TaskConfig:
    return _task_config("maintenance-check", "automated", 1)


@pytest.fixture
def settings() -> AppSettings:
    return AppSettings()


@pytest.fixture
def task(
    maintenance_config: TaskConfig, settings: AppSettings, mocker
) -> MaintenanceCheckTask:
    """
    A minimal task instance - sufficient for the helper-method tests below,
    none of which read self.state/self.tasks_config/self.scheduler.
    """
    mocker.patch(_PATCH_CONFIG_LOADER)
    return MaintenanceCheckTask(maintenance_config, settings)


@pytest.fixture
def task_with_thresholds(
    maintenance_config: TaskConfig, mocker
) -> MaintenanceCheckTask:
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
def make_task(
    maintenance_config: TaskConfig, settings: AppSettings, mocker
) -> MaintenanceCheckTaskFactory:
    """Builds a task and swaps in real tasks_config/state/scheduler."""

    def _make(
        tasks_config: TasksConfig | None = None,
        state: AppState | None = None,
        task_settings: AppSettings | None = None,
    ) -> MaintenanceCheckTask:
        mocker.patch(_PATCH_CONFIG_LOADER)
        built = MaintenanceCheckTask(maintenance_config, task_settings or settings)
        built.tasks_config = tasks_config or TasksConfig(tasks={})
        built.state = state or AppState()
        built.scheduler = TaskScheduler(built.tasks_config, built.state)
        return built

    return _make


def _settings(
    show_notifications: bool = True,
    output_mode: str = "terminal",
    notification_level: str = "warning",
) -> AppSettings:
    return AppSettings(
        maintenance_check=MaintenanceCheckSettings(
            show_notifications=show_notifications,
            output_mode=output_mode,
            notification_level=notification_level,
        )
    )


@pytest.fixture
def settings_with_tmp_reports(mocker, tmp_path) -> AppSettings:
    """Real report_dir under tmp_path, for genuine file I/O tests."""
    mocker.patch.object(AppSettings, "home_dir", property(lambda _: tmp_path))
    settings = AppSettings()
    settings.ensure_directories()
    return settings


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
    def test_none_raises_value_error(self, automated_task: TaskConfig):
        with pytest.raises(ValueError):
            MaintenanceCheckTask._format_overdue_description(automated_task, None)

    def test_zero_days_is_due_today(self, automated_task: TaskConfig):
        """
        Regression test for the fix: previously unreachable, since the
        outer truthy check excluded 0 before this branch could run,
        silently returning None instead.
        """
        result = MaintenanceCheckTask._format_overdue_description(automated_task, 0)
        assert result == f"Task `{automated_task.name}` is due today"

    def test_one_day_singular(self, automated_task: TaskConfig):
        result = MaintenanceCheckTask._format_overdue_description(automated_task, 1)
        assert result == f"Task `{automated_task.name}` is overdue by 1 day"

    def test_multiple_days_plural(self, automated_task: TaskConfig):
        result = MaintenanceCheckTask._format_overdue_description(automated_task, 5)
        assert result == f"Task `{automated_task.name}` is overdue by 5 days"


# ---------------------------------------------------------------------------
# _check_broken_timer
# ---------------------------------------------------------------------------


class TestCheckBrokenTimer:
    def test_none_raises_value_error(self):
        with pytest.raises(ValueError):
            MaintenanceCheckTask._check_broken_timer(
                None,
                [],
                timer_threshold_days=10,
                task_name="test-task",
                task_state=AppState().get_task_state("test-task"),
            )

    def test_zero_days_overdue_does_not_raise_or_append(self):
        """
        0 days overdue is completely valid (just due today) and
        shouldn't raise an error and shouldn't append to issues.
        """
        issues: list[MaintenanceIssue] = []
        MaintenanceCheckTask._check_broken_timer(
            0,
            issues,
            timer_threshold_days=10,
            task_name="test-task",
            task_state=AppState().get_task_state("test-task"),
        )
        assert not issues

    def test_below_threshold_appends_nothing(self):
        issues: list[MaintenanceIssue] = []
        MaintenanceCheckTask._check_broken_timer(
            5,
            issues,
            timer_threshold_days=10,
            task_name="test-task",
            task_state=AppState().get_task_state("test-task"),
        )
        assert not issues

    def test_above_threshold_appends_critical_issue(self):
        issues: list[MaintenanceIssue] = []
        state = AppState()
        state.update_task_state(
            task_name="update-mirrorlist", status=TaskStatus.FAILURE
        )

        MaintenanceCheckTask._check_broken_timer(
            20,
            issues,
            timer_threshold_days=10,
            task_name="update-mirrorlist",
            task_state=state.get_task_state("update-mirrorlist"),
        )

        assert len(issues) == 1
        assert issues[0].severity == IssueSeverity.CRITICAL
        assert issues[0].task_name == "update-mirrorlist"
        assert issues[0].days_overdue == 20


# ---------------------------------------------------------------------------
# _determine_severity
# ---------------------------------------------------------------------------


class TestDetermineSeverity:
    def test_none_returns_info(self, task_with_thresholds: MaintenanceCheckTask):
        assert task_with_thresholds._determine_severity(None) == IssueSeverity.INFO

    def test_zero_returns_info(self, task_with_thresholds: MaintenanceCheckTask):
        assert task_with_thresholds._determine_severity(0) == IssueSeverity.INFO

    def test_below_warning_threshold_returns_info(
        self, task_with_thresholds: MaintenanceCheckTask
    ):
        assert task_with_thresholds._determine_severity(2) == IssueSeverity.INFO

    def test_at_warning_threshold_returns_warning(
        self, task_with_thresholds: MaintenanceCheckTask
    ):
        assert task_with_thresholds._determine_severity(5) == IssueSeverity.WARNING

    def test_at_critical_threshold_returns_critical(
        self, task_with_thresholds: MaintenanceCheckTask
    ):
        assert task_with_thresholds._determine_severity(10) == IssueSeverity.CRITICAL

    def test_above_critical_threshold_returns_critical(
        self, task_with_thresholds: MaintenanceCheckTask
    ):
        assert task_with_thresholds._determine_severity(20) == IssueSeverity.CRITICAL


# ---------------------------------------------------------------------------
# _check_failed_automated_task
# ---------------------------------------------------------------------------


class TestCheckFailedAutomatedTask:
    def test_due_appends_warning_issue(self, task: MaintenanceCheckTask):
        issues: list[MaintenanceIssue] = []
        state = AppState()
        state.update_task_state(
            task_name="update-mirrorlist", status=TaskStatus.FAILURE
        )
        schedule_info = _schedule_info("update-mirrorlist", is_due=True)

        task._check_failed_automated_task(
            days_overdue=2,
            issues=issues,
            schedule_info=schedule_info,
            task_name="update-mirrorlist",
            task_state=state.get_task_state("update-mirrorlist"),
        )

        assert len(issues) == 1
        assert issues[0].severity == IssueSeverity.WARNING

    def test_not_due_appends_nothing(self, task: MaintenanceCheckTask):
        issues: list[MaintenanceIssue] = []
        state = AppState()
        state.update_task_state(
            task_name="update-mirrorlist", status=TaskStatus.FAILURE
        )
        schedule_info = _schedule_info("update-mirrorlist", is_due=False)

        task._check_failed_automated_task(
            days_overdue=None,
            issues=issues,
            schedule_info=schedule_info,
            task_name="update-mirrorlist",
            task_state=state.get_task_state("update-mirrorlist"),
        )

        assert not issues


# ---------------------------------------------------------------------------
# _categorize_issues
# ---------------------------------------------------------------------------


class TestCategorizeIssues:
    @pytest.mark.parametrize(
        "severity,list_attr",
        [
            (IssueSeverity.CRITICAL, "critical_issues"),
            (IssueSeverity.WARNING, "warning_issues"),
            (IssueSeverity.INFO, "info_issues"),
        ],
    )
    def test_routes_to_correct_list(self, severity, list_attr):
        issue = MaintenanceIssue(
            task_name="x", severity=severity, description="d", recommendation="r"
        )
        result = MaintenanceCheckResult(status=TaskStatus.SUCCESS)

        MaintenanceCheckTask._categorize_issues([issue], result)

        assert getattr(result, list_attr) == [issue]


# ---------------------------------------------------------------------------
# _check_task
# ---------------------------------------------------------------------------


class TestCheckTask:
    def test_never_run_task_returns_single_info_issue(
        self, make_task: MaintenanceCheckTaskFactory
    ):
        config = _task_config("test-task", "automated")
        tasks_config = TasksConfig(tasks={config.name: config})
        task = make_task(tasks_config=tasks_config)  # fresh AppState -> never run

        issues = task._check_task(config.name, config)

        assert len(issues) == 1
        assert issues[0].severity == IssueSeverity.INFO
        assert "never been executed" in issues[0].description

    def test_manual_task_not_due_returns_no_issues(
        self, make_task: MaintenanceCheckTaskFactory
    ):
        config = _task_config("test-task", "manual", frequency=30)
        tasks_config = TasksConfig(tasks={config.name: config})
        state = AppState()
        state.update_task_state(
            task_name=config.name,
            status=TaskStatus.SUCCESS,
            next_due=datetime.now() + timedelta(days=10),
        )
        task = make_task(tasks_config=tasks_config, state=state)

        assert task._check_task(config.name, config) == []

    def test_manual_task_due_returns_warning_issue(
        self, make_task: MaintenanceCheckTaskFactory
    ):
        config = _task_config("test-task", "manual", frequency=30)
        tasks_config = TasksConfig(tasks={config.name: config})
        state = AppState()
        state.update_task_state(
            task_name=config.name,
            status=TaskStatus.SUCCESS,
            next_due=datetime.now() - timedelta(days=3),
        )
        task = make_task(tasks_config=tasks_config, state=state)

        issues = task._check_task(config.name, config)

        assert len(issues) == 1
        assert issues[0].severity == IssueSeverity.WARNING
        assert issues[0].task_name == config.name

    @pytest.mark.parametrize(
        "status",
        [
            TaskStatus.SUCCESS,
            TaskStatus.PARTIAL,
            TaskStatus.SKIPPED,
        ],
    )
    def test_automated_task_overdue_but_not_failed_returns_single_issue(
        self, make_task: MaintenanceCheckTaskFactory, status
    ):

        config = _task_config("test-task", "automated", frequency=7)
        tasks_config = TasksConfig(tasks={config.name: config})
        state = AppState()
        state.update_task_state(
            task_name=config.name,
            status=status,
            next_due=datetime.now() - timedelta(days=15),
        )
        task: MaintenanceCheckTask = make_task(tasks_config=tasks_config, state=state)

        issues = task._check_task(config.name, config)

        assert len(issues) == 1
        assert issues[0].severity == IssueSeverity.CRITICAL
        assert issues[0].task_name == config.name
        assert "overdue" in issues[0].description

    def test_automated_task_overdue_and_failed_returns_both_issues(
        self, make_task: MaintenanceCheckTaskFactory
    ):
        """
        An automated task that is overdue and failed should return two issues; One
        WARNING for failed automated task, and one CRITICAL for broken timer.
        """
        config = _task_config("test-task", "automated", frequency=7)
        tasks_config = TasksConfig(tasks={config.name: config})
        state = AppState()
        state.update_task_state(
            task_name=config.name,
            status=TaskStatus.FAILURE,
            next_due=datetime.now() - timedelta(days=20),  # beyond 7*1.5=10.5 threshold
        )
        task: MaintenanceCheckTask = make_task(tasks_config=tasks_config, state=state)

        issues = task._check_task(config.name, config)

        assert len(issues) == 2
        assert issues[0].severity == IssueSeverity.WARNING
        assert issues[1].severity == IssueSeverity.CRITICAL
        assert "failed" in issues[0].description
        assert "broken" in issues[1].description

    def test_automated_task_failed_and_due_returns_warning_issue(
        self, make_task: MaintenanceCheckTaskFactory
    ):
        config = _task_config("test-task", "automated", frequency=7)
        tasks_config = TasksConfig(tasks={config.name: config})
        state = AppState()
        state.update_task_state(
            task_name=config.name,
            status=TaskStatus.FAILURE,
            next_due=datetime.now()
            - timedelta(days=2),  # due, below 7*1.5=10.5 threshold
        )
        task: MaintenanceCheckTask = make_task(tasks_config=tasks_config, state=state)

        issues = task._check_task(config.name, config)

        assert len(issues) == 1
        assert issues[0].severity == IssueSeverity.WARNING
        assert "failed" in issues[0].description


# ---------------------------------------------------------------------------
# execute
# ---------------------------------------------------------------------------


class TestExecute:
    def test_no_issues_returns_success(self, make_task: MaintenanceCheckTaskFactory):
        config = _task_config("config-backup", "manual", frequency=30)
        tasks_config = TasksConfig(tasks={config.name: config})
        state = AppState()
        state.update_task_state(
            task_name=config.name,
            status=TaskStatus.SUCCESS,
            next_due=datetime.now() + timedelta(days=10),
        )
        task = make_task(tasks_config=tasks_config, state=state)

        task_result = task.execute()
        assert task_result.details is not None
        maintenance_check_result = task_result.details.maintenance_result

        assert task_result.status == TaskStatus.SUCCESS
        assert maintenance_check_result is not None
        assert maintenance_check_result.total_tasks_monitored == 1
        assert not maintenance_check_result.has_issues

    def test_skips_checking_itself(
        self, make_task: MaintenanceCheckTaskFactory, maintenance_config: TaskConfig
    ):
        """
        The maintenance-check task itself must never appear in its own
        issue list, even though it's an enabled task like any other - a
        fresh (never-run) state would otherwise produce an INFO issue.
        """
        tasks_config = TasksConfig(tasks={maintenance_config.name: maintenance_config})
        task = make_task(tasks_config=tasks_config)

        task_result = task.execute()
        assert task_result.details is not None
        maintenance_check_result = task_result.details.maintenance_result

        assert maintenance_check_result is not None
        assert maintenance_check_result.total_tasks_monitored == 1
        assert not maintenance_check_result.has_issues

    def test_critical_issue_sets_failure_status(
        self, make_task: MaintenanceCheckTaskFactory
    ):
        config = _task_config("mirrorlist-update", "automated", frequency=7)
        tasks_config = TasksConfig(tasks={config.name: config})
        state = AppState()
        state.update_task_state(
            task_name=config.name,
            status=TaskStatus.FAILURE,
            next_due=datetime.now() - timedelta(days=20),
        )
        task = make_task(tasks_config=tasks_config, state=state)

        task_result = task.execute()
        assert task_result.details is not None
        maintenance_check_result = task_result.details.maintenance_result

        assert task_result.status == TaskStatus.FAILURE
        assert maintenance_check_result is not None
        assert maintenance_check_result.error_message is not None

    def test_warning_only_sets_partial_status(
        self, make_task: MaintenanceCheckTaskFactory
    ):
        config = _task_config("mirrorlist-update", "automated", frequency=7)
        tasks_config = TasksConfig(tasks={config.name: config})
        state = AppState()
        state.update_task_state(
            task_name=config.name,
            status=TaskStatus.FAILURE,
            next_due=datetime.now() - timedelta(days=2),
        )
        task = make_task(tasks_config=tasks_config, state=state)

        task_result = task.execute()

        assert task_result.status == TaskStatus.PARTIAL

    def test_info_only_sets_success_status(
        self, make_task: MaintenanceCheckTaskFactory
    ):
        """A never-run task produces only an INFO issue - status stays SUCCESS."""
        config = _task_config("mirrorlist-update", "automated", frequency=7)
        tasks_config = TasksConfig(tasks={config.name: config})
        task = make_task(tasks_config=tasks_config)

        task_result = task.execute()
        assert task_result.details is not None
        maintenance_check_result = task_result.details.maintenance_result

        assert task_result.status == TaskStatus.SUCCESS
        assert maintenance_check_result is not None
        assert maintenance_check_result.info_issues

    def test_details_carries_maintenance_result(
        self, make_task: MaintenanceCheckTaskFactory
    ):
        task = make_task()

        task_result = task.execute()
        assert task_result.details is not None
        maintenance_check_result = task_result.details.maintenance_result

        assert maintenance_check_result is task.maintenance_check_result


# ---------------------------------------------------------------------------
# post_execute
# ---------------------------------------------------------------------------


class TestPostExecute:
    def test_raises_when_maintenance_check_result_is_none(
        self, task: MaintenanceCheckTask
    ):
        task.maintenance_check_result = None

        with pytest.raises(ValueError):
            task.post_execute(MagicMock(spec=TaskResult))

    def test_sends_notification_when_show_notifications_true(
        self, make_task: MaintenanceCheckTaskFactory, mocker
    ):
        task: MaintenanceCheckTask = make_task(
            task_settings=_settings(show_notifications=True)
        )
        task.maintenance_check_result = MaintenanceCheckResult(
            status=TaskStatus.SUCCESS
        )
        mock_notify: MagicMock = mocker.patch.object(task, "_send_notification")
        mocker.patch.object(task, "_save_report")

        task.post_execute(MagicMock(spec=TaskResult))

        mock_notify.assert_called_once_with(task.maintenance_check_result)

    def test_skips_notification_when_show_notifications_false(
        self, make_task: MaintenanceCheckTaskFactory, mocker
    ):
        task = make_task(task_settings=_settings(show_notifications=False))
        task.maintenance_check_result = MaintenanceCheckResult(
            status=TaskStatus.SUCCESS
        )
        mock_notify = mocker.patch.object(task, "_send_notification")
        mocker.patch.object(task, "_save_report")

        task.post_execute(MagicMock(spec=TaskResult))

        mock_notify.assert_not_called()

    @pytest.mark.parametrize("output_mode", ["file", "both"])
    def test_saves_report_when_output_mode_requires_it(
        self, make_task: MaintenanceCheckTaskFactory, mocker, output_mode
    ):
        task = make_task(
            task_settings=_settings(show_notifications=False, output_mode=output_mode)
        )
        task.maintenance_check_result = MaintenanceCheckResult(
            status=TaskStatus.SUCCESS
        )
        mocker.patch.object(task, "_send_notification")
        mock_save = mocker.patch.object(task, "_save_report")

        task.post_execute(MagicMock())

        mock_save.assert_called_once_with(task.maintenance_check_result)

    def test_skips_report_when_output_mode_is_terminal(
        self, make_task: MaintenanceCheckTaskFactory, mocker
    ):
        task = make_task(
            task_settings=_settings(show_notifications=False, output_mode="terminal")
        )
        task.maintenance_check_result = MaintenanceCheckResult(
            status=TaskStatus.SUCCESS
        )
        mocker.patch.object(task, "_send_notification")
        mock_save = mocker.patch.object(task, "_save_report")

        task.post_execute(MagicMock(spec=TaskResult))

        mock_save.assert_not_called()


# ---------------------------------------------------------------------------
# _send_notification
# ---------------------------------------------------------------------------


class TestSendNotification:
    def test_no_issues_does_not_notify(
        self, make_task: MaintenanceCheckTaskFactory, mocker
    ):
        task: MaintenanceCheckTask = make_task()
        task.notification_manager = MagicMock(spec=NotificationManager)
        mock_send: MagicMock = mocker.patch.object(
            task.notification_manager, "send_maintenance_notification"
        )
        result = MaintenanceCheckResult(status=TaskStatus.SUCCESS)

        task._send_notification(result)

        mock_send.assert_not_called()

    def test_info_issue_below_warning_threshold_does_not_notify(
        self, make_task: MaintenanceCheckTaskFactory, mocker
    ):
        """Default notification_level='warning' - an INFO-only result sits
        below that threshold and should not trigger a notification."""
        task: MaintenanceCheckTask = make_task(
            task_settings=_settings(notification_level="warning")
        )
        task.notification_manager = MagicMock(spec=NotificationManager)
        mock_send: MagicMock = mocker.patch.object(
            task.notification_manager, "send_maintenance_notification"
        )
        issue = MaintenanceIssue(
            task_name="x",
            severity=IssueSeverity.INFO,
            description="d",
            recommendation="r",
        )
        result = MaintenanceCheckResult(status=TaskStatus.SUCCESS, info_issues=[issue])

        task._send_notification(result)

        mock_send.assert_not_called()

    def test_issue_at_notification_threshold_notifies(
        self, make_task: MaintenanceCheckTaskFactory
    ):
        task: MaintenanceCheckTask = make_task(
            task_settings=_settings(notification_level="warning")
        )
        task.notification_manager = MagicMock(spec=NotificationManager)
        mock_manager: MagicMock = task.notification_manager
        issue = MaintenanceIssue(
            task_name="x",
            severity=IssueSeverity.WARNING,
            description="d",
            recommendation="r",
        )
        result = MaintenanceCheckResult(
            status=TaskStatus.PARTIAL, warning_issues=[issue]
        )

        task._send_notification(result)

        mock_manager.send_maintenance_notification.assert_called_once_with(
            severity=IssueSeverity.WARNING,
            tasks_count=1,
            summary=result.summary_message,
        )

    def test_critical_issue_notifies_even_at_highest_threshold(
        self, make_task: MaintenanceCheckTaskFactory
    ):
        task: MaintenanceCheckTask = make_task(
            task_settings=_settings(notification_level="critical")
        )
        task.notification_manager = MagicMock(spec=NotificationManager)
        mock_manager: MagicMock = task.notification_manager
        issue = MaintenanceIssue(
            task_name="x",
            severity=IssueSeverity.CRITICAL,
            description="d",
            recommendation="r",
        )
        result = MaintenanceCheckResult(
            status=TaskStatus.FAILURE, critical_issues=[issue]
        )

        task._send_notification(result)

        mock_manager.send_maintenance_notification.assert_called_once()


# ---------------------------------------------------------------------------
# _save_report
# ---------------------------------------------------------------------------


class TestSaveReport:
    def test_creates_report_file(
        self,
        make_task: MaintenanceCheckTaskFactory,
        settings_with_tmp_reports: AppSettings,
    ):
        task: MaintenanceCheckTask = make_task(task_settings=settings_with_tmp_reports)
        result = MaintenanceCheckResult(status=TaskStatus.SUCCESS)

        task._save_report(result)

        report_files = list(
            settings_with_tmp_reports.report_dir.glob("maintenance-check_*.txt")
        )
        assert len(report_files) == 1

    def test_healthy_report_shows_no_issues_message(
        self,
        make_task: MaintenanceCheckTaskFactory,
        settings_with_tmp_reports: AppSettings,
    ):
        task: MaintenanceCheckTask = make_task(task_settings=settings_with_tmp_reports)
        result = MaintenanceCheckResult(status=TaskStatus.SUCCESS)

        task._save_report(result)

        content = next(settings_with_tmp_reports.report_dir.glob("*.txt")).read_text()
        assert "No maintenance issues found" in content

    def test_report_includes_issue_sections_by_severity(
        self,
        make_task: MaintenanceCheckTaskFactory,
        settings_with_tmp_reports: AppSettings,
    ):
        task: MaintenanceCheckTask = make_task(task_settings=settings_with_tmp_reports)
        issue = MaintenanceIssue(
            task_name="update-mirrorlist",
            severity=IssueSeverity.CRITICAL,
            description="severely overdue",
            recommendation="run it now",
        )
        result = MaintenanceCheckResult(
            status=TaskStatus.FAILURE, critical_issues=[issue]
        )

        task._save_report(result)

        content = next(settings_with_tmp_reports.report_dir.glob("*.txt")).read_text()
        assert "CRITICAL ISSUES" in content
        assert "update-mirrorlist" in content
        assert "severely overdue" in content
        assert "run it now" in content

    def test_report_omits_absent_severity_sections(
        self,
        make_task: MaintenanceCheckTaskFactory,
        settings_with_tmp_reports: AppSettings,
    ):
        task: MaintenanceCheckTask = make_task(task_settings=settings_with_tmp_reports)
        issue = MaintenanceIssue(
            task_name="x",
            severity=IssueSeverity.INFO,
            description="d",
            recommendation="r",
        )
        result = MaintenanceCheckResult(status=TaskStatus.SUCCESS, info_issues=[issue])

        task._save_report(result)

        content = next(settings_with_tmp_reports.report_dir.glob("*.txt")).read_text()
        assert "CRITICAL ISSUES" not in content
        assert "WARNING ISSUES" not in content
        assert "INFORMATION" in content

    def test_calls_cleanup_old_reports(
        self,
        make_task: MaintenanceCheckTaskFactory,
        settings_with_tmp_reports: AppSettings,
        mocker,
    ):
        task: MaintenanceCheckTask = make_task(task_settings=settings_with_tmp_reports)
        mock_cleanup: MagicMock = mocker.patch.object(task, "_cleanup_old_reports")
        result = MaintenanceCheckResult(status=TaskStatus.SUCCESS)

        task._save_report(result)

        mock_cleanup.assert_called_once()


# ---------------------------------------------------------------------------
# _format_issue_text
# ---------------------------------------------------------------------------


class TestFormatIssueText:
    def test_includes_all_optional_fields_when_present(self):
        issue = MaintenanceIssue(
            task_name="update-mirrorlist",
            severity=IssueSeverity.WARNING,
            description="overdue",
            days_overdue=3,
            last_run=datetime(2026, 6, 1, 10, 0, 0),
            last_status=TaskStatus.FAILURE,
            recommendation="run it",
        )

        text = "\n".join(MaintenanceCheckTask._format_issue_text(issue))

        assert "Days Overdue: 3" in text
        assert "Last Run: 2026-06-01 10:00:00" in text
        assert "Last Status: failure" in text
        assert "Recommendation: run it" in text

    def test_omits_optional_fields_when_absent(self):
        issue = MaintenanceIssue(
            task_name="x",
            severity=IssueSeverity.INFO,
            description="d",
            recommendation="r",
        )

        text = "\n".join(MaintenanceCheckTask._format_issue_text(issue))

        assert "Days Overdue" not in text
        assert "Last Run" not in text
        assert "Last Status" not in text

    def test_days_overdue_zero_is_still_shown(self):
        issue = MaintenanceIssue(
            task_name="x",
            severity=IssueSeverity.INFO,
            description="d",
            days_overdue=0,
            recommendation="r",
        )

        text = "\n".join(MaintenanceCheckTask._format_issue_text(issue))

        assert "Days Overdue: 0" in text


# ---------------------------------------------------------------------------
# _cleanup_old_reports
# ---------------------------------------------------------------------------


class TestCleanupOldReports:
    def test_returns_early_if_report_dir_missing(
        self, make_task: MaintenanceCheckTaskFactory, mocker, tmp_path
    ):
        mocker.patch.object(
            AppSettings, "home_dir", property(lambda _: tmp_path / "does-not-exist")
        )
        task: MaintenanceCheckTask = make_task(task_settings=AppSettings())

        task._cleanup_old_reports()  # must not raise

    def test_deletes_files_older_than_retention(
        self,
        make_task: MaintenanceCheckTaskFactory,
        settings_with_tmp_reports: AppSettings,
    ):
        old_file = settings_with_tmp_reports.report_dir / "maintenance-check_old.txt"
        old_file.write_text("old")
        retention = settings_with_tmp_reports.maintenance_check.report_retention_days
        old_time = (datetime.now() - timedelta(days=retention + 5)).timestamp()
        os.utime(old_file, (old_time, old_time))
        task = make_task(task_settings=settings_with_tmp_reports)

        task._cleanup_old_reports()

        assert not old_file.exists()

    def test_keeps_files_within_retention(
        self,
        make_task: MaintenanceCheckTaskFactory,
        settings_with_tmp_reports: AppSettings,
    ):
        recent_file = (
            settings_with_tmp_reports.report_dir / "maintenance-check_recent.txt"
        )
        recent_file.write_text("recent")  # mtime defaults to now - within retention
        task: MaintenanceCheckTask = make_task(task_settings=settings_with_tmp_reports)

        task._cleanup_old_reports()

        assert recent_file.exists()

    def test_ignores_non_matching_filenames(
        self,
        make_task: MaintenanceCheckTaskFactory,
        settings_with_tmp_reports: AppSettings,
    ):
        other_file: Path = settings_with_tmp_reports.report_dir / "unrelated.txt"
        other_file.write_text("x")
        old_time = (datetime.now() - timedelta(days=999)).timestamp()
        os.utime(other_file, (old_time, old_time))
        task: MaintenanceCheckTask = make_task(task_settings=settings_with_tmp_reports)

        task._cleanup_old_reports()

        assert other_file.exists()  # glob only matches "maintenance-check_*.txt"

    def test_per_file_failure_does_not_stop_cleanup_of_others(
        self,
        make_task: MaintenanceCheckTaskFactory,
        settings_with_tmp_reports: AppSettings,
        mocker,
    ):
        old1: Path = settings_with_tmp_reports.report_dir / "maintenance-check_a.txt"
        old2: Path = settings_with_tmp_reports.report_dir / "maintenance-check_b.txt"
        old1.write_text("a")
        old2.write_text("b")
        old_time = (datetime.now() - timedelta(days=999)).timestamp()
        os.utime(old1, (old_time, old_time))
        os.utime(old2, (old_time, old_time))

        original_unlink = Path.unlink

        def flaky_unlink(self, *args, **kwargs):
            if self.name == "maintenance-check_a.txt":
                raise PermissionError("nope")
            return original_unlink(self, *args, **kwargs)

        mocker.patch.object(Path, "unlink", flaky_unlink)
        task: MaintenanceCheckTask = make_task(task_settings=settings_with_tmp_reports)

        task._cleanup_old_reports()  # must not raise

        assert old1.exists()  # failed to delete, still present
        assert not old2.exists()  # successfully deleted
