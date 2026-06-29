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
    TasksConfig,
    TaskStatus,
    create_default_config_files,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config_dir(tmp_path) -> Path:
    """Provides an isolated configuration directory."""
    d: Path = tmp_path / "archcare_config"
    d.mkdir()
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
