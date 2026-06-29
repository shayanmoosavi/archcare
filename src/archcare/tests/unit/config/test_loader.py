"""Unit tests for ConfigLoader and configuration initialization."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import tomli_w

from archcare.config import (
    AppSettings,
    AppState,
    ConfigLoader,
    LogLevel,
    TasksConfig,
    TaskStatus,
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

    def test_valid_file_parses_tasks_correctly(
        self, loader: ConfigLoader, config_dir: Path
    ):
        tasks_toml: dict[str, Any] = {
            "test-task": {
                "type": "automated",
                "frequency": 7,
                "description": "A test task",
                "command": "test-task",
                "enabled": True,
            }
        }
        tasks_file: Path = config_dir / "tasks.toml"
        with open(tasks_file, "wb") as f:
            tomli_w.dump(tasks_toml, f)

        config: TasksConfig = loader.load_tasks()
        assert "test-task" in config.tasks
        assert config.tasks["test-task"].frequency == 7

    def test_toml_decode_error_returns_empty_config(
        self, loader: ConfigLoader, config_dir: Path
    ):
        """A syntactically invalid TOML file should gracefully return empty tasks."""
        tasks_file: Path = config_dir / "tasks.toml"
        tasks_file.write_text("[broken toml\nkey = value")

        config: TasksConfig = loader.load_tasks()
        assert config.tasks == {}

    def test_validation_error_returns_empty_config(
        self, loader: ConfigLoader, config_dir: Path
    ):
        """A valid TOML file with wrong schema types should return empty tasks."""
        tasks_toml: dict[str, Any] = {
            "test-task": {
                "type": "automated",
                "frequency": "not-an-integer",  # Causes ValidationError
                "description": "A test task",
                "command": "test-task",
                "enabled": True,
            }
        }
        tasks_file: Path = config_dir / "tasks.toml"
        with open(tasks_file, "wb") as f:
            tomli_w.dump(tasks_toml, f)

        config: TasksConfig = loader.load_tasks()
        assert config.tasks == {}


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
        services_file = config_dir / "ignored-services.toml"
        with open(services_file, "wb") as f:
            tomli_w.dump({"services": ["NetworkManager-wait-online.service"]}, f)

        config = loader.load_ignored_services()
        assert "NetworkManager-wait-online.service" in config.services

    def test_toml_decode_error_returns_empty_list(
        self, loader: ConfigLoader, config_dir: Path
    ):
        services_file = config_dir / "ignored-services.toml"
        services_file.write_text("services = [unclosed array")

        config = loader.load_ignored_services()
        assert config.services == []

    def test_validation_error_returns_empty_list(
        self, loader: ConfigLoader, config_dir: Path
    ):
        services_file = config_dir / "ignored-services.toml"
        # Should be a list of strings, passing an int
        with open(services_file, "wb") as f:
            tomli_w.dump({"services": 123}, f)

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

    def test_valid_file_overrides_defaults(
        self, loader: ConfigLoader, config_dir: Path
    ):
        settings_toml = {"log_level": "DEBUG", "dry_run": True}
        settings_file = config_dir / "settings.toml"
        with open(settings_file, "wb") as f:
            tomli_w.dump(settings_toml, f)

        settings = loader.load_settings()
        assert settings.log_level == LogLevel.DEBUG
        assert settings.dry_run is True

    def test_toml_decode_error_returns_defaults(
        self, loader: ConfigLoader, config_dir: Path
    ):
        settings_file = config_dir / "settings.toml"
        settings_file.write_text("invalid syntax = =")

        settings = loader.load_settings()
        default_settings = loader.load_default_settings()
        assert settings == default_settings

    def test_validation_error_returns_defaults(
        self, loader: ConfigLoader, config_dir: Path
    ):
        settings_toml = {"log_retention_days": "seven"}  # Expected int
        settings_file = config_dir / "settings.toml"
        with open(settings_file, "wb") as f:
            tomli_w.dump(settings_toml, f)

        settings = loader.load_settings()
        # Should fallback gracefully rather than raising ValidationError
        assert isinstance(settings.log_retention_days, int)

    def test_save_and_load_roundtrip(self, loader, config_dir):
        settings = AppSettings(
            user="testuser", log_level=LogLevel.WARNING, dry_run=True
        )
        loader.save_settings(settings)

        fresh_loader = ConfigLoader(user="testuser", config_dir=config_dir)
        loaded = fresh_loader.load_settings()

        assert loaded.log_level == LogLevel.WARNING
        assert loaded.dry_run is True
