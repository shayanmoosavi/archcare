"""Unit tests for config/models.py."""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from archcare.config import (
    AppSettings,
    AppState,
    IgnoredServicesConfig,
    SkipReason,
    TaskConfig,
    TasksConfig,
    TaskStatus,
)
from archcare.config.exceptions import (
    HomeDirectoryResolutionError,
    InvalidTaskTypeFilterError,
    UnknownTaskError,
)
from archcare.config.models import HealthCheckSettings, MaintenanceCheckSettings, MirrorlistSettings

# Test-specific constants for HealthCheckSettings validation tests (below/above thresholds)
TEST_WARNING_PERCENT = 70
TEST_CRITICAL_PERCENT = 90

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_sudo_user(monkeypatch):
    monkeypatch.delenv("SUDO_USER", raising=False)


@pytest.fixture
def mock_pwd(mocker) -> MagicMock:
    return mocker.patch("archcare.config.models.getpwnam")


# ---------------------------------------------------------------------------
# TaskConfig
# ---------------------------------------------------------------------------


class TestTaskConfig:
    def test_valid_config_is_accepted(self, automated_task: TaskConfig):
        DEFAULT_AUTOMATED_FREQUENCY = 7

        assert automated_task.name == "test-auto-task"
        assert automated_task.enabled is True
        assert automated_task.frequency == DEFAULT_AUTOMATED_FREQUENCY

    def test_name_with_spaces_raises(self):
        with pytest.raises(ValidationError):
            _make_task(name="task with spaces")

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
    def test_get_task_returns_matching_config(
        self, tasks_config: TasksConfig, automated_task: TaskConfig
    ):
        result = tasks_config.get_task(automated_task.name)
        assert result == automated_task

    def test_get_task_raises_for_unknown_name(self, tasks_config: TasksConfig):
        with pytest.raises(UnknownTaskError):
            tasks_config.get_task("does-not-exist")

    def test_get_enabled_tasks_excludes_disabled(
        self, automated_task: TaskConfig, disabled_task: TaskConfig
    ):
        config = TasksConfig(
            tasks={
                automated_task.name: automated_task,
                disabled_task.name: disabled_task,
            }
        )
        enabled = config.get_enabled_tasks()
        assert automated_task.name in enabled
        assert disabled_task.name not in enabled

    def test_get_enabled_tasks_includes_all_when_all_enabled(self, tasks_config: TasksConfig):
        assert len(tasks_config.get_enabled_tasks()) == len(tasks_config.tasks)

    def test_get_tasks_by_type_returns_automated(
        self,
        tasks_config: TasksConfig,
        automated_task: TaskConfig,
        manual_task: TaskConfig,
    ):
        result = tasks_config.get_tasks_by_type("automated")
        assert automated_task.name in result
        assert manual_task.name not in result

    def test_get_tasks_by_type_returns_manual(
        self,
        tasks_config: TasksConfig,
        automated_task: TaskConfig,
        manual_task: TaskConfig,
    ):
        result = tasks_config.get_tasks_by_type("manual")
        assert manual_task.name in result
        assert automated_task.name not in result

    def test_get_tasks_by_type_raises_for_invalid_type(self, tasks_config: TasksConfig):
        with pytest.raises(InvalidTaskTypeFilterError):
            tasks_config.get_tasks_by_type("weekly")

    def test_empty_config_has_no_enabled_tasks(self, empty_tasks_config: TasksConfig):
        assert empty_tasks_config.get_enabled_tasks() == {}


# ---------------------------------------------------------------------------
# AppSettings — path computation
# ---------------------------------------------------------------------------


class TestAppSettingsPaths:
    def test_home_dir_is_path_home_when_user_is_none(self):
        settings = AppSettings(user=None)
        assert settings.home_dir == Path.home()

    def test_home_dir_uses_user_name(self, mock_pwd: MagicMock):
        mock_pwd.return_value.pw_dir = "/home/alice"

        settings = AppSettings(user="alice")

        assert settings.home_dir == Path("/home/alice")
        assert mock_pwd.call_args_list[0].args[0] == "alice"

    def test_prefers_sudo_user(self, monkeypatch, mock_pwd: MagicMock):
        monkeypatch.setenv("SUDO_USER", "bob")
        mock_pwd.return_value.pw_dir = "/home/bob"

        settings = AppSettings(user="alice")

        assert settings.home_dir == Path("/home/bob")

    def test_resolve_user_home_uses_pwd(self, mock_pwd: MagicMock):
        """_resolve_user_home calls pwd.getpwnam and returns pw_dir."""
        mock_pwd.return_value.pw_dir = "/var/lib/custom"

        result = AppSettings._resolve_user_home("alice")
        assert result == Path("/var/lib/custom")

    def test_resolve_user_home_fallback_when_user_not_found(self, mock_pwd: MagicMock, mocker):
        """_resolve_user_home returns home directory when user is not found."""
        mock_pwd.side_effect = KeyError("unknown")
        mocker.patch.object(Path, "exists", return_value=True)

        result = AppSettings._resolve_user_home("unknown")
        assert result == Path("/home/unknown")

    def test_resolve_user_home_raises_when_no_fallback(self, mock_pwd: MagicMock, mocker):
        """_resolve_user_home raises when no fallback is available."""
        mock_pwd.side_effect = KeyError("ghost")
        mocker.patch.object(Path, "exists", return_value=False)

        with pytest.raises(HomeDirectoryResolutionError, match="Cannot resolve home directory"):
            AppSettings._resolve_user_home("ghost")

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("log_dir", Path("/home/alice/.local/state/archcare/logs")),
            ("config_dir", Path("/home/alice/.config/archcare")),
            ("report_dir", Path("/home/alice/.local/state/archcare/reports")),
            ("state_file", Path("/home/alice/.local/state/archcare/state.json")),
        ],
    )
    def test_paths_are_under_home(self, path, expected, mock_pwd: MagicMock):
        mock_pwd.return_value.pw_dir = "/home/alice"
        settings = AppSettings(user="alice")
        assert getattr(settings, path) == expected


class TestValidatePaths:
    def test_validate_paths_accepts_valid_paths(self, mock_pwd: MagicMock):
        """Valid absolute paths should pass validation."""
        mock_pwd.return_value.pw_dir = "/home/alice"

        # Should not raise
        settings = AppSettings(user="alice")
        assert settings.home_dir == Path("/home/alice")

    def test_validate_paths_rejects_relative_paths(self, monkeypatch):
        """Relative paths should raise ValidationError."""
        # Force Path.home() to return a relative path
        monkeypatch.setattr(Path, "home", staticmethod(lambda: Path("relative/path")))

        with pytest.raises(ValidationError, match="Path must be absolute"):
            AppSettings(user=None)

    def test_validate_paths_rejects_unresolvable_paths(self, mock_pwd: MagicMock, mocker):
        """Unresolvable paths should raise ValidationError."""
        mock_pwd.return_value.pw_dir = "/home/alice"

        original_resolve = Path.resolve

        def failing_resolve(self, strict=False):
            if ".local" in str(self):  # Target one of the computed paths
                raise OSError("Invalid path")
            return original_resolve(self, strict=strict)

        mocker.patch.object(Path, "resolve", failing_resolve)

        with pytest.raises(ValidationError, match="Malformed path"):
            AppSettings(user="alice")


class TestAppSettingsEnsureDirectories:
    def test_all_required_directories_are_created(self, tmp_path, monkeypatch):
        """
        Redirect Path.home() to tmp_path so ensure_directories() writes to a
        temp location instead of the real home directory.
        """
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
        settings = AppSettings(user=None)

        settings.ensure_directories()

        assert settings.log_dir.exists()
        assert settings.config_dir.exists()
        assert settings.state_file.parent.exists()
        assert settings.report_dir.exists()

    def test_ensure_directories_is_idempotent(self, tmp_path, monkeypatch):
        """Calling twice must not raise even if directories already exist."""
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
        settings = AppSettings(user=None)

        settings.ensure_directories()
        settings.ensure_directories()  # must not raise


# ---------------------------------------------------------------------------
# AppState
# ---------------------------------------------------------------------------


class TestAppState:
    def test_get_task_state_creates_new_state_for_unknown_task(self, fresh_state: AppState):
        state = fresh_state.get_task_state("brand-new")
        assert state.last_run is None
        assert state.run_count == 0

    def test_get_task_state_returns_same_object_each_time(self, fresh_state: AppState):
        first = fresh_state.get_task_state("some-task")
        second = fresh_state.get_task_state("some-task")
        assert first is second

    def test_update_sets_last_run_to_now(self, fresh_state: AppState):
        before = datetime.now()
        _update(fresh_state, "task-a", TaskStatus.SUCCESS)
        assert fresh_state.get_task_state("task-a").last_run >= before  # ty:ignore[unsupported-operator]

    def test_update_records_status(self, fresh_state: AppState):
        _update(fresh_state, "task-a", TaskStatus.FAILURE)
        assert fresh_state.get_task_state("task-a").last_status == TaskStatus.FAILURE

    def test_run_count_increments_on_each_update(self, fresh_state: AppState):
        RUN_COUNT = 3
        for _ in range(RUN_COUNT):
            _update(fresh_state, "task-a", TaskStatus.SUCCESS)
        assert fresh_state.get_task_state("task-a").run_count == RUN_COUNT

    def test_update_stores_next_due(self, fresh_state: AppState):
        due = datetime.now() + timedelta(days=7)
        _update(fresh_state, "task-a", TaskStatus.SUCCESS, next_due=due)
        assert fresh_state.get_task_state("task-a").next_due == due

    def test_update_stores_error_message(self, fresh_state: AppState):
        _update(fresh_state, "task-a", TaskStatus.FAILURE, error="timeout")
        assert fresh_state.get_task_state("task-a").last_error == "timeout"

    def test_update_stores_skip_reason(self, fresh_state: AppState):
        _update(
            fresh_state,
            "task-a",
            TaskStatus.SKIPPED,
            skip_reason=SkipReason.NOT_DUE,
        )
        assert fresh_state.get_task_state("task-a").skip_reason == SkipReason.NOT_DUE

    def test_independent_tasks_have_independent_state(self, fresh_state: AppState):
        _update(fresh_state, "task-a", TaskStatus.SUCCESS)
        _update(fresh_state, "task-b", TaskStatus.FAILURE)
        assert fresh_state.get_task_state("task-a").last_status == TaskStatus.SUCCESS
        assert fresh_state.get_task_state("task-b").last_status == TaskStatus.FAILURE


# ---------------------------------------------------------------------------
# IgnoredServicesConfig validators
# ---------------------------------------------------------------------------


class TestIgnoredServicesConfig:
    def test_valid_services_accepted(self):
        config = IgnoredServicesConfig(services=["service-a.service", "template@instance.service"])
        assert config.services == ["service-a.service", "template@instance.service"]

    def test_invalid_services_raises(self):
        with pytest.raises(ValidationError):
            IgnoredServicesConfig(services=["invalid"])


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

    def test_backup_retention_count_default(self):
        DEFAULT_BACKUP_RETENTION = 5
        assert MirrorlistSettings().backup_retention_count == DEFAULT_BACKUP_RETENTION

    @pytest.mark.parametrize("value", [1, 5, 10, 100])
    def test_valid_backup_retention_accepted(self, value):
        assert MirrorlistSettings(backup_retention_count=value).backup_retention_count == value

    @pytest.mark.parametrize("value", [0, -1])
    def test_invalid_backup_retention_rejected(self, value):
        with pytest.raises(ValidationError):
            MirrorlistSettings(backup_retention_count=value)


# ---------------------------------------------------------------------------
# HealthCheckSettings validators
# ---------------------------------------------------------------------------


class TestHealthCheckSettings:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("cpu_warning_percent", 0),
            ("cpu_warning_percent", 100),
            ("swap_warning_percent", 0),
            ("swap_warning_percent", 100),
        ],
    )
    def test_valid_percentages_accepted(self, field, value):
        settings = HealthCheckSettings(**{field: value})
        assert getattr(settings, field) == value

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("cpu_warning_percent", -1),
            ("cpu_warning_percent", 101),
            ("swap_warning_percent", -1),
            ("swap_warning_percent", 101),
        ],
    )
    def test_invalid_percentages_rejected(self, field, value):
        with pytest.raises(ValidationError):
            HealthCheckSettings(**{field: value})

    @pytest.mark.parametrize(
        ("critical", "warning"),
        [
            (50, 0),
            (100, 0),
            (100, 50),
            (100, 99),
        ],
    )
    def test_valid_memory_threshold_combinations(self, critical, warning):
        settings = HealthCheckSettings(
            memory_critical_percent=critical, memory_warning_percent=warning
        )
        assert settings.memory_critical_percent == critical
        assert settings.memory_warning_percent == warning

    @pytest.mark.parametrize(
        ("critical", "warning"),
        [
            (50, 0),
            (100, 0),
            (100, 50),
            (100, 99),
        ],
    )
    def test_valid_disk_threshold_combinations(self, critical, warning):
        settings = HealthCheckSettings(disk_critical_percent=critical, disk_warning_percent=warning)
        assert settings.disk_critical_percent == critical
        assert settings.disk_warning_percent == warning

    @pytest.mark.parametrize(
        ("critical", "warning"),
        [
            (0, 0),  # warning >= critical (equal)
            (50, 50),  # equal
            (50, 60),  # warning > critical
            (90, 95),  # warning > critical
            (90, 90),  # equal
        ],
    )
    def test_invalid_memory_threshold_combinations_rejected(self, critical, warning):
        with pytest.raises(
            ValidationError, match="memory_warning_percent must be < memory_critical_percent"
        ):
            HealthCheckSettings(memory_critical_percent=critical, memory_warning_percent=warning)

    @pytest.mark.parametrize(
        ("critical", "warning"),
        [
            (0, 0),  # warning >= critical (equal)
            (50, 50),  # equal
            (50, 60),  # warning > critical
            (90, 95),  # warning > critical
            (90, 90),  # equal
        ],
    )
    def test_invalid_disk_threshold_combinations_rejected(self, critical, warning):
        with pytest.raises(
            ValidationError, match="disk_warning_percent must be < disk_critical_percent"
        ):
            HealthCheckSettings(disk_critical_percent=critical, disk_warning_percent=warning)

    def test_memory_warning_below_critical_accepted(self):
        settings = HealthCheckSettings(
            memory_warning_percent=TEST_WARNING_PERCENT,
            memory_critical_percent=TEST_CRITICAL_PERCENT,
        )
        assert settings.memory_warning_percent == TEST_WARNING_PERCENT
        assert settings.memory_critical_percent == TEST_CRITICAL_PERCENT

    def test_disk_warning_below_critical_accepted(self):
        settings = HealthCheckSettings(
            disk_warning_percent=TEST_WARNING_PERCENT,
            disk_critical_percent=TEST_CRITICAL_PERCENT,
        )
        assert settings.disk_warning_percent == TEST_WARNING_PERCENT
        assert settings.disk_critical_percent == TEST_CRITICAL_PERCENT

    def test_memory_warning_not_below_critical_rejected(self):
        with pytest.raises(
            ValidationError, match="memory_warning_percent must be < memory_critical_percent"
        ):
            HealthCheckSettings(memory_warning_percent=95, memory_critical_percent=90)

    def test_memory_warning_equal_critical_rejected(self):
        with pytest.raises(
            ValidationError, match="memory_warning_percent must be < memory_critical_percent"
        ):
            HealthCheckSettings(memory_warning_percent=90, memory_critical_percent=90)

    def test_disk_warning_not_below_critical_rejected(self):
        with pytest.raises(
            ValidationError, match="disk_warning_percent must be < disk_critical_percent"
        ):
            HealthCheckSettings(disk_warning_percent=95, disk_critical_percent=90)

    def test_disk_warning_equal_critical_rejected(self):
        with pytest.raises(
            ValidationError, match="disk_warning_percent must be < disk_critical_percent"
        ):
            HealthCheckSettings(disk_warning_percent=90, disk_critical_percent=90)

    def test_defaults_values(self):
        DEFAULT_CPU_WARNING = 90
        DEFAULT_MEM_CRITICAL = 90
        DEFAULT_MEM_WARNING = 80
        DEFAULT_SWAP_WARNING = 50
        DEFAULT_DISK_CRITICAL = 90
        DEFAULT_DISK_WARNING = 80

        s = HealthCheckSettings()
        assert s.cpu_warning_percent == DEFAULT_CPU_WARNING
        assert s.memory_critical_percent == DEFAULT_MEM_CRITICAL
        assert s.memory_warning_percent == DEFAULT_MEM_WARNING
        assert s.swap_warning_percent == DEFAULT_SWAP_WARNING
        assert s.disk_critical_percent == DEFAULT_DISK_CRITICAL
        assert s.disk_warning_percent == DEFAULT_DISK_WARNING


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
        assert MaintenanceCheckSettings(notification_level=level).notification_level == level

    def test_invalid_notification_level_raises(self):
        with pytest.raises(ValidationError):
            MaintenanceCheckSettings(notification_level="debug")

    @pytest.mark.parametrize(("critical", "warning"), [(7, 0), (10, 5), (1, 0), (30, 29)])
    def test_valid_threshold_combinations_accepted(self, critical, warning):
        settings = MaintenanceCheckSettings(
            critical_threshold_days=critical, warning_threshold_days=warning
        )
        assert settings.critical_threshold_days == critical
        assert settings.warning_threshold_days == warning

    def test_default_thresholds_satisfy_constraint(self):
        settings = MaintenanceCheckSettings()
        assert settings.warning_threshold_days < settings.critical_threshold_days

    @pytest.mark.parametrize(("critical", "warning"), [(7, 7), (5, 10), (0, 1)])
    def test_warning_not_below_critical_raises(self, critical, warning):
        """Cross-field rule: warning_threshold_days must be strictly below
        critical_threshold_days (equal or reversed values are rejected)."""
        with pytest.raises(ValidationError, match="must be less than"):
            MaintenanceCheckSettings(
                critical_threshold_days=critical, warning_threshold_days=warning
            )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _make_task(**overrides) -> TaskConfig:
    """Build a minimal TaskConfig, merging any overrides."""
    from archcare.config import TaskConfig

    defaults = {
        "name": "test-task",
        "type": "automated",
        "frequency": 7,
        "description": "A test task",
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
) -> None:
    """Thin wrapper so test bodies stay single-line."""
    state.update_task_state(
        task_name=task_name,
        status=status,
        next_due=next_due,
        error=error,
        skip_reason=skip_reason,
    )
