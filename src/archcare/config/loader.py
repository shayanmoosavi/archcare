"""
Configuration loader for archcare.

Handles loading and parsing TOML configuration files into Pydantic models.
"""

import json
import tomllib
from pathlib import Path
from typing import Any

import tomli_w
from loguru import logger
from pydantic import ValidationError

from .models import (
    AppSettings,
    AppState,
    CacheCleanupConfig,
    IgnoredServicesConfig,
    MirrorlistSettings,
    MaintenanceCheckSettings,
    TaskConfig,
    TasksConfig,
)


class ConfigLoader:
    """Loads and manages application configuration."""

    def __init__(self, user: str | None = None, config_dir: Path | None = None):
        """
        Initialize config loader.

        Args:
            user: Username of the user
            config_dir: Override default config directory
        """
        # Use default settings to get config_dir if not provided
        self.user = user
        default_settings = AppSettings(user=user)
        self.config_dir = config_dir or default_settings.config_dir
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def load_tasks(self, tasks_file: Path | None = None) -> TasksConfig:
        """
        Load task configurations from TOML file.

        Args:
            tasks_file: Path to tasks.toml (defaults to config_dir/tasks.toml)

        Returns:
            TasksConfig object with all task definitions

        Raises:
            FileNotFoundError: If tasks file doesn't exist
            ValueError: If TOML is invalid or doesn't match schema
        """
        tasks_path = tasks_file or self.config_dir / "tasks.toml"

        if not tasks_path.exists():
            logger.warning(f"Tasks file not found: {tasks_path}")
            return TasksConfig(tasks={})

        logger.info(f"Loading tasks from: {tasks_path}")

        with open(tasks_path, "rb") as f:
            data = tomllib.load(f)

        tasks_dict = {}

        for section_name, section_data in data.items():
            if isinstance(section_data, dict):
                # Add the section name as the task name
                task_data = {**section_data, "name": section_name}
                tasks_dict[section_name] = TaskConfig(**task_data)

        config = TasksConfig(tasks=tasks_dict)
        logger.info(
            f"Loaded {len(config.tasks)} tasks ({len(config.get_enabled_tasks())} enabled)"
        )

        return config

    def load_ignored_services(
        self, services_file: Path | None = None
    ) -> IgnoredServicesConfig:
        """
        Load ignored services configuration.

        Args:
            services_file: Path to ignored-services.toml

        Returns:
            IgnoredServicesConfig object
        """
        services_path = services_file or self.config_dir / "ignored-services.toml"

        if not services_path.exists():
            logger.warning(f"Ignored services file not found: {services_path}")
            return IgnoredServicesConfig(services=[])

        logger.info(f"Loading ignored services from: {services_path}")

        with open(services_path, "rb") as f:
            data = tomllib.load(f)

        # Expected format: services = ["service1", "service2"]
        config = IgnoredServicesConfig(**data)
        logger.info(f"Loaded {len(config.services)} ignored services")

        return config

    def load_settings(self, settings_file: Path | None = None) -> AppSettings:
        """
        Load application settings.

        Args:
            settings_file: Path to settings.toml (optional, uses defaults if not found)

        Returns:
            AppSettings object
        """
        from archcare.utils.output import print_error

        settings_path = settings_file or self.config_dir / "settings.toml"

        if not settings_path.exists():
            logger.info("Settings file not found, using defaults")
            return self.load_default_settings()

        logger.info(f"Loading settings from: {settings_path}")

        with open(settings_path, "rb") as f:
            data = tomllib.load(f)

        try:
            settings_data: dict[str, Any] = {"user": self.user}

            # Copy global settings
            for key in [
                "log_level",
                "log_retention_days",
                "require_confirmation",
                "dry_run",
            ]:
                if key in data:
                    settings_data[key] = data[key]

            # Load mirrorlist settings if present
            if "mirrorlist" in data:
                settings_data["mirrorlist"] = MirrorlistSettings(**data["mirrorlist"])

            # Load maintenance check settings if present
            if "maintenance_check" in data:
                settings_data["maintenance_check"] = MaintenanceCheckSettings(
                    **data["maintenance_check"]
                )

            settings = AppSettings(**settings_data)
            settings.ensure_directories()

        # Load default settings if settings.toml is invalid
        except ValidationError as e:
            logger.error("Invalid settings.toml")
            print_error(f"{e}")
            logger.warning("Using default settings")
            return self.load_default_settings()

        return settings

    def load_default_settings(self) -> AppSettings:
        """
        Load the default settings

        Returns:
            settings: The AppSettings object with default values
        """
        settings = AppSettings(user=self.user)
        settings.ensure_directories()
        return settings

    def save_settings(
        self, settings: AppSettings, settings_file: Path | None = None
    ) -> None:
        """
        Save application settings to TOML file.

        Args:
            settings: AppSettings object to save
            settings_file: Path to settings.toml
        """
        settings_path = settings_file or self.config_dir / "settings.toml"

        # Convert to dict and handle Path objects
        data = settings.model_dump()

        logger.info(f"Saving settings to: {settings_path}")

        with open(settings_path, "wb") as f:
            tomli_w.dump(data, f)

    def load_state(self, state_file: Path | None = None) -> AppState:
        """
        Load application state from JSON file.

        Args:
            state_file: Path to state.json (uses settings default if None)

        Returns:
            AppState object
        """
        settings = self.load_settings()
        state_path = state_file or settings.state_file

        if not state_path.exists():
            logger.info("State file not found, creating new state")
            return AppState()

        logger.info(f"Loading state from: {state_path}")

        with open(state_path, "r") as f:
            data = json.load(f)

        return AppState(**data)

    def save_state(self, state: AppState, state_file: Path | None = None) -> None:
        """
        Save application state to JSON file.

        Args:
            state: AppState object to save
            state_file: Path to state.json
        """
        settings = self.load_settings()
        state_path = state_file or settings.state_file
        state_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Saving state to: {state_path}")

        # Use model_dump with mode='json' to handle datetime serialization
        data = state.model_dump(mode="json")

        with open(state_path, "w") as f:
            json.dump(data, f, indent=4)


def create_default_config_files(config_dir: Path) -> None:
    """
    Create default configuration files if they don't exist.

    This is a helper function to bootstrap a new installation.

    Args:
        config_dir: Directory to create config files in
    """
    config_dir.mkdir(parents=True, exist_ok=True)
    default_config_dir = Path(__file__).parent

    # Create default tasks.toml
    tasks_path = config_dir / "tasks.toml"
    if not tasks_path.exists():
        with open(default_config_dir / "tasks.toml", "rb") as f:
            data = tomllib.load(f)

        default_tasks = tomli_w.dumps(data)
        tasks_path.write_text(default_tasks)
        logger.info(f"Created default tasks.toml at {tasks_path}")

    # Create default ignored-services.toml
    services_path = config_dir / "ignored-services.toml"
    if not services_path.exists():
        with open(default_config_dir / "ignored-services.toml", "rb") as f:
            data = tomllib.load(f)

        default_services = tomli_w.dumps(data)
        services_path.write_text(default_services)
        logger.info(f"Created default ignored-services.toml at {services_path}")

    # Create default settings.toml
    settings_path = config_dir / "settings.toml"
    if not settings_path.exists():
        with open(default_config_dir / "settings.toml", "rb") as f:
            data = tomllib.load(f)

        default_settings = tomli_w.dumps(data)
        settings_path.write_text(default_settings)
        logger.info(f"Created default settings.toml at {settings_path}")
