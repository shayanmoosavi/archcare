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
def make_task(maintenance_config: TaskConfig, settings: AppSettings, mocker):
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
    def test_never_run_task_returns_single_info_issue(self, make_task):
        config = _task_config("test-task", "test-task", "automated")
        tasks_config = TasksConfig(tasks={config.name: config})
        task = make_task(tasks_config=tasks_config)  # fresh AppState -> never run

        issues = task._check_task(config.name, config)

        assert len(issues) == 1
        assert issues[0].severity == IssueSeverity.INFO
        assert "never been executed" in issues[0].description

    def test_manual_task_not_due_returns_no_issues(self, make_task):
        config = _task_config("test-task", "test-task", "manual", frequency=30)
        tasks_config = TasksConfig(tasks={config.name: config})
        state = AppState()
        state.update_task_state(
            task_name=config.name,
            status=TaskStatus.SUCCESS,
            next_due=datetime.now() + timedelta(days=10),
        )
        task = make_task(tasks_config=tasks_config, state=state)

        assert task._check_task(config.name, config) == []

    def test_manual_task_due_returns_warning_issue(self, make_task):
        config = _task_config("test-task", "test-task", "manual", frequency=30)
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
        self, make_task, status
    ):

        config = _task_config("test-task", "test-task", "automated", frequency=7)
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

    def test_automated_task_overdue_and_failed_returns_both_issues(self, make_task):
        """
        An automated task that is overdue and failed should return two issues; One
        WARNING for failed automated task, and one CRITICAL for broken timer.
        """
        config = _task_config("test-task", "test-task", "automated", frequency=7)
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

    def test_automated_task_failed_and_due_returns_warning_issue(self, make_task):
        config = _task_config("test-task", "test-task", "automated", frequency=7)
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
    def test_no_issues_returns_success(self, make_task):
        config = _task_config("config-backup", "backup-config", "manual", frequency=30)
        tasks_config = TasksConfig(tasks={config.name: config})
        state = AppState()
        state.update_task_state(
            task_name=config.name,
            status=TaskStatus.SUCCESS,
            next_due=datetime.now() + timedelta(days=10),
        )
        task = make_task(tasks_config=tasks_config, state=state)

        task_result = task.execute()

        assert task_result.status == TaskStatus.SUCCESS
        assert task.maintenance_check_result.total_tasks_monitored == 1
        assert not task.maintenance_check_result.has_issues

    def test_skips_checking_itself(self, make_task, maintenance_config: TaskConfig):
        """
        The maintenance-check task itself must never appear in its own
        issue list, even though it's an enabled task like any other - a
        fresh (never-run) state would otherwise produce an INFO issue.
        """
        tasks_config = TasksConfig(tasks={maintenance_config.name: maintenance_config})
        task = make_task(tasks_config=tasks_config)

        task.execute()

        assert task.maintenance_check_result.total_tasks_monitored == 1
        assert not task.maintenance_check_result.has_issues

    def test_critical_issue_sets_failure_status(self, make_task):
        config = _task_config(
            "mirrorlist-update", "update-mirrorlist", "automated", frequency=7
        )
        tasks_config = TasksConfig(tasks={config.name: config})
        state = AppState()
        state.update_task_state(
            task_name=config.name,
            status=TaskStatus.FAILURE,
            next_due=datetime.now() - timedelta(days=20),
        )
        task = make_task(tasks_config=tasks_config, state=state)

        task_result = task.execute()

        assert task_result.status == TaskStatus.FAILURE
        assert task.maintenance_check_result.error_message is not None

    def test_warning_only_sets_partial_status(self, make_task):
        config = _task_config(
            "mirrorlist-update", "update-mirrorlist", "automated", frequency=7
        )
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

    def test_info_only_sets_success_status(self, make_task):
        """A never-run task produces only an INFO issue - status stays SUCCESS."""
        config = _task_config(
            "mirrorlist-update", "update-mirrorlist", "automated", frequency=7
        )
        tasks_config = TasksConfig(tasks={config.name: config})
        task = make_task(tasks_config=tasks_config)

        task_result = task.execute()

        assert task_result.status == TaskStatus.SUCCESS
        assert task.maintenance_check_result.info_issues

    def test_details_carries_maintenance_result(self, make_task):
        task = make_task()

        task_result = task.execute()

        assert (
            task_result.details["maintenance_result"] is task.maintenance_check_result
        )
