"""Unit tests for ConfigLoader and configuration initialization."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from archcare.config import (
    AppSettings,
    AppState,
    ConfigLoader,
    LogLevel,
    TasksConfig,
    TaskStatus,
    TaskType,
    create_default_config_files,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_home_dir(monkeypatch, tmp_path):
    """
    Prevent AppSettings from hitting the real /home directory.
    By patching the property descriptor on the class, we force all derived
    paths (config, state, logs, reports) to safely build inside tmp_path.
    """
    home_dir: Path = tmp_path / "home/testuser"
    monkeypatch.setattr(AppSettings, "home_dir", property(lambda _: home_dir))
    return home_dir


@pytest.fixture
def config_dir(mock_home_dir) -> Path:
    """Provides an isolated configuration directory."""
    d: Path = mock_home_dir / ".config/archcare"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def loader(config_dir: Path) -> ConfigLoader:
    """ConfigLoader instance bound to the temporary config directory."""
    return ConfigLoader(user="testuser", config_dir=config_dir)


@pytest.fixture
def state_file(tmp_path) -> Path:
    """Explicit state file path in tmp_path passed to load_state/save_state."""
    return tmp_path / "state.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _w(path: Path, content: str) -> None:
    """Write content to path."""
    path.write_text(content)


# Minimal valid task block reused across test classes
_TASK_TOML = """\
[test-task]
type = "automated"
frequency = 7
description = "A test task"
command = "test-task"
enabled = true
"""

_BAD_TOML = "[[[ this is not valid toml"

# ---------------------------------------------------------------------------
# ConfigLoader.__init__
# ---------------------------------------------------------------------------


class TestConfigLoaderInit:
    def test_creates_config_dir_when_absent(self, tmp_path):
        config_dir: Path = tmp_path / "new" / "archcare"
        ConfigLoader(config_dir=config_dir)
        assert config_dir.exists()

    def test_accepts_existing_config_dir(self, config_dir: Path):
        loader = ConfigLoader(config_dir=config_dir)
        assert loader.config_dir == config_dir


# ---------------------------------------------------------------------------
# ConfigLoader.load_tasks
# ---------------------------------------------------------------------------


class TestLoadTasks:
    def test_missing_file_returns_empty_config(self, loader: ConfigLoader):
        config: TasksConfig = loader.load_tasks()
        assert config.tasks == {}

    def test_empty_file_returns_empty_config(
        self, loader: ConfigLoader, config_dir: Path
    ):
        tasks_file: Path = config_dir / "tasks.toml"
        tasks_file.touch()
        config: TasksConfig = loader.load_tasks(tasks_file)
        assert config.tasks == {}

    def test_toml_decode_error_returns_empty_config(
        self, loader: ConfigLoader, config_dir: Path
    ):
        """A syntactically invalid TOML file should gracefully return empty tasks."""
        tasks_file: Path = config_dir / "tasks.toml"
        _w(tasks_file, _BAD_TOML)

        config: TasksConfig = loader.load_tasks()
        assert config.tasks == {}

    def test_validation_error_returns_empty_config(
        self, loader: ConfigLoader, config_dir: Path
    ):
        """A valid TOML file with wrong schema types should return empty tasks."""
        # frequency = -1 fails TaskConfig validation
        _w(
            config_dir / "tasks.toml",
            """\
[bad-task]
type = "automated"
frequency = -1
description = "Bad"
command = "bad-task"
enabled = true
""",
        )

        config: TasksConfig = loader.load_tasks()
        assert config.tasks == {}

    def test_valid_file_parses_single_task_correctly(
        self, loader: ConfigLoader, config_dir: Path
    ):
        tasks_file: Path = config_dir / "tasks.toml"
        _w(tasks_file, _TASK_TOML)

        config: TasksConfig = loader.load_tasks()
        assert "test-task" in config.tasks

        test_task = config.tasks["test-task"]
        assert test_task.task_type == TaskType.AUTOMATED
        assert test_task.frequency == 7
        assert test_task.description == "A test task"
        assert test_task.command == "test-task"
        assert test_task.enabled is True

    def test_loads_multiple_tasks(self, config_dir: Path, loader: ConfigLoader):
        _w(
            config_dir / "tasks.toml",
            _TASK_TOML
            + """\
[second-task]
type = "manual"
frequency = 30
description = "Second"
command = "second-task"
enabled = true
""",
        )

        assert len(loader.load_tasks().tasks) == 2


# ---------------------------------------------------------------------------
# ConfigLoader.load_ignored_services
# ---------------------------------------------------------------------------


class TestLoadIgnoredServices:
    def test_missing_file_returns_empty_list(self, loader: ConfigLoader):
        config = loader.load_ignored_services()
        assert config.services == []

    def test_empty_file_returns_empty_list(
        self, loader: ConfigLoader, config_dir: Path
    ):
        services_file: Path = config_dir / "ignored-services.toml"
        services_file.touch()
        config = loader.load_ignored_services(services_file)
        assert config.services == []

    def test_valid_file_loads_services(self, loader: ConfigLoader, config_dir: Path):
        _w(
            config_dir / "ignored-services.toml",
            'services = ["nginx.service", "apache2.service"]\n',
        )
        config = loader.load_ignored_services()
        assert "apache2.service" in config.services

    def test_toml_decode_error_returns_empty_list(
        self, loader: ConfigLoader, config_dir: Path
    ):
        _w(config_dir / "ignored-services.toml", _BAD_TOML)
        config = loader.load_ignored_services()
        assert config.services == []

    def test_validation_error_returns_empty_list(
        self, loader: ConfigLoader, config_dir: Path
    ):
        # Should be a list of strings, passing an int
        _w(config_dir / "ignored-services.toml", "services = 123")

        config = loader.load_ignored_services()
        assert config.services == []


# ---------------------------------------------------------------------------
# Loading / Saving Settings
# ---------------------------------------------------------------------------


class TestConfigLoaderSettings:
    def test_missing_file_returns_defaults(self, loader: ConfigLoader):
        settings = loader.load_settings()
        default_settings = loader.load_default_settings()
        assert settings == default_settings

    def test_empty_file_returns_defaults(self, loader: ConfigLoader, config_dir: Path):
        settings_file = config_dir / "settings.toml"
        settings_file.touch()

        settings = loader.load_settings()
        default_settings = loader.load_default_settings()
        assert settings == default_settings

    def test_toml_decode_error_returns_defaults(
        self, loader: ConfigLoader, config_dir: Path
    ):
        _w(config_dir / "settings.toml", _BAD_TOML)

        settings = loader.load_settings()
        default_settings = loader.load_default_settings()
        assert settings == default_settings

    def test_validation_error_returns_defaults(
        self, loader: ConfigLoader, config_dir: Path
    ):
        # Expected int
        _w(config_dir / "settings.toml", 'log_retention_days = "seven"\n')

        settings = loader.load_settings()
        # Should fallback gracefully rather than raising ValidationError
        assert isinstance(settings.log_retention_days, int)

    def test_valid_file_overrides_defaults(
        self, loader: ConfigLoader, config_dir: Path
    ):
        settings_toml = """\
log_level = "DEBUG"
dry_run = true
"""
        _w(config_dir / "settings.toml", settings_toml)

        settings = loader.load_settings()
        assert settings.log_level == LogLevel.DEBUG
        assert settings.dry_run is True

    def test_parses_mirrorlist_section(self, loader: ConfigLoader, config_dir: Path):
        _w(
            config_dir / "settings.toml",
            """\
[mirrorlist]
country = "France"
protocol = "https"
sort = "age"
latest = 10
number_of_mirrors = 3
""",
        )
        settings = loader.load_settings()
        assert settings.mirrorlist.country == "France"
        assert settings.mirrorlist.number_of_mirrors == 3

    def test_falls_back_to_defaults_on_invalid_value(
        self, loader: ConfigLoader, config_dir: Path
    ):
        _w(config_dir / "settings.toml", 'log_level = "VERBOSE"\n')
        assert loader.load_settings().log_level.value == "INFO"

    def test_parses_maintenance_check_section(
        self, loader: ConfigLoader, config_dir: Path
    ):
        _w(
            config_dir / "settings.toml",
            """\
[maintenance_check]
output_mode = "file"
require_acknowledgment = false
""",
        )
        settings = loader.load_settings()
        assert settings.maintenance_check.output_mode == "file"
        assert settings.maintenance_check.require_acknowledgment is False

    def test_updates_cached_settings_after_loading(
        self, loader: ConfigLoader, config_dir: Path
    ):
        _w(config_dir / "settings.toml", "log_retention_days = 99\n")
        loader.load_settings()
        assert loader._settings.log_retention_days == 99

    def test_save_and_load_roundtrip(self, loader: ConfigLoader, config_dir: Path):
        settings = AppSettings(
            user="testuser", log_level=LogLevel.WARNING, dry_run=True
        )
        loader.save_settings(settings)

        fresh_loader = ConfigLoader(user="testuser", config_dir=config_dir)
        loaded = fresh_loader.load_settings()

        assert loaded.log_level == LogLevel.WARNING
        assert loaded.dry_run is True


# ---------------------------------------------------------------------------
# Loading / Saving State
# ---------------------------------------------------------------------------


class TestStateManagement:
    def test_returns_fresh_state_when_file_absent(
        self, loader: ConfigLoader, state_file: Path
    ):
        state = loader.load_state(state_file=state_file)
        assert isinstance(state, AppState)
        assert state.tasks == {}

    def test_returns_fresh_state_on_corrupt_json(
        self, loader: ConfigLoader, state_file: Path
    ):
        state_file.write_text("{{{ not json")
        assert loader.load_state(state_file=state_file).tasks == {}

    def test_returns_fresh_state_on_invalid_structure(
        self, loader: ConfigLoader, state_file: Path
    ):
        # tasks should be a dict; passing a string triggers ValidationError
        state_file.write_text('{"tasks": "should be a dict not a string"}')
        result = loader.load_state(state_file=state_file)
        assert isinstance(result, AppState)
        assert result.tasks == {}

    def test_round_trip_preserves_last_status(
        self, loader: ConfigLoader, state_file: Path
    ):
        state = AppState()
        state.update_task_state(
            task_name="test-task",
            status=TaskStatus.SUCCESS,
            next_due=datetime.now() + timedelta(days=7),
            error=None,
            skip_reason=None,
            skip_message=None,
        )
        loader.save_state(state, state_file=state_file)

        reloaded = loader.load_state(state_file=state_file)
        assert reloaded.get_task_state("test-task").last_status == TaskStatus.SUCCESS

    def test_round_trip_preserves_run_count(
        self, loader: ConfigLoader, state_file: Path
    ):
        state = AppState()
        for _ in range(3):
            state.update_task_state(
                task_name="test-task",
                status=TaskStatus.SUCCESS,
                next_due=None,
                error=None,
                skip_reason=None,
                skip_message=None,
            )
        loader.save_state(state, state_file=state_file)

        reloaded = loader.load_state(state_file=state_file)
        assert reloaded.get_task_state("test-task").run_count == 3

    def test_save_creates_parent_directory(self, loader: ConfigLoader, tmp_path):
        nested = tmp_path / "deep" / "nested" / "state.json"
        loader.save_state(AppState(), state_file=nested)
        assert nested.exists()

    def test_saved_file_is_valid_json(self, loader: ConfigLoader, state_file: Path):
        loader.save_state(AppState(), state_file=state_file)
        data = json.loads(state_file.read_text())
        assert "tasks" in data
        assert "last_updated" in data


# ---------------------------------------------------------------------------
# create_default_config_files
# ---------------------------------------------------------------------------


class TestCreateDefaultConfigFiles:
    def test_creates_settings_toml(self, tmp_path):
        create_default_config_files(tmp_path)
        assert (tmp_path / "settings.toml").exists()

    def test_creates_tasks_toml(self, tmp_path):
        create_default_config_files(tmp_path)
        assert (tmp_path / "tasks.toml").exists()

    def test_creates_ignored_services_toml(self, tmp_path):
        create_default_config_files(tmp_path)
        assert (tmp_path / "ignored-services.toml").exists()

    def test_does_not_overwrite_existing_files_without_force(self, tmp_path):
        sentinel = "sentinel content"
        (tmp_path / "settings.toml").write_text(sentinel)
        create_default_config_files(tmp_path, force=False)
        assert (tmp_path / "settings.toml").read_text() == sentinel

    def test_overwrites_existing_files_with_force(self, tmp_path):
        (tmp_path / "settings.toml").write_text("sentinel content")
        create_default_config_files(tmp_path, force=True)
        assert (tmp_path / "settings.toml").read_text() != "sentinel content"

    def test_creates_config_dir_when_absent(self, tmp_path):
        config_dir = tmp_path / "new" / "archcare"
        create_default_config_files(config_dir)
        assert config_dir.exists()

    def test_created_settings_toml_is_valid_toml(self, tmp_path):
        import tomllib

        create_default_config_files(tmp_path)
        with open(tmp_path / "settings.toml", "rb") as f:
            data = tomllib.load(f)
        assert isinstance(data, dict)

    def test_created_tasks_toml_is_valid_toml(self, tmp_path):
        import tomllib

        create_default_config_files(tmp_path)
        with open(tmp_path / "tasks.toml", "rb") as f:
            data = tomllib.load(f)
        assert isinstance(data, dict)
