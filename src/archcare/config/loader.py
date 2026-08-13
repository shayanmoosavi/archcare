"""
Configuration loader for archcare.

Handles loading and parsing TOML configuration files into Pydantic models.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import ValidationError
from tomlkit import TOMLDocument, dumps, parse, table
from tomlkit.exceptions import ParseError

from . import defaults
from .models import (
    AppSettings,
    AppState,
    IgnoredServicesConfig,
    MaintenanceCheckSettings,
    MirrorlistSettings,
    TaskConfig,
    TasksConfig,
)


def _load_document(path: Path, default_builder: Callable[[], TOMLDocument]) -> TOMLDocument:
    """
    Load `path` as a TOMLDocument if it exists, otherwise build the default document
    using `default_builder`.

    Args:
        path (pathlib.Path): The path to load the document from
        default_builder (Callable[[], TOMLDocument]): The function to call to build
         the default document

    Returns:
        TOMLDocument: The loaded document
    """
    if path.exists():
        return parse(path.read_text())
    return default_builder()


def _patch_document(doc: dict[str, Any], data: dict[str, Any]) -> None:
    """
    Apply values from `data` onto an existing TOMLDocument/Table in place,
    recursing into nested dicts so only actually-changed leaf values are
    touched.

    Args:
        doc (dict[str, Any]): The document/table to patch
        data (dict[str, Any]): The data to apply
    """
    for key, value in data.items():
        if isinstance(value, dict):
            if key not in doc or not isinstance(doc[key], dict):
                doc[key] = table()
            _patch_document(doc[key], value)
        else:
            doc[key] = value


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
        self._settings: AppSettings = AppSettings(user=user)
        self.config_dir = config_dir or self._settings.config_dir
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def load_tasks(self, tasks_file: Path | None = None) -> TasksConfig:
        """
        Load task configurations from TOML file.

        Args:
            tasks_file: Path to tasks.toml (defaults to config_dir/tasks.toml)

        Returns:
            TasksConfig object with all task definitions
        """
        tasks_path = tasks_file or self.config_dir / "tasks.toml"

        if not tasks_path.exists():
            logger.error(f"Tasks file not found: {tasks_path}")
            return TasksConfig(tasks={})

        logger.info(f"Loading tasks from: {tasks_path}")

        try:
            doc = parse(tasks_path.read_text())

            if not doc:
                logger.error(f"Tasks file is empty: {tasks_path}")
                return TasksConfig(tasks={})

            tasks_dict = {}

            for section_name, section_data in doc.items():
                if isinstance(section_data, dict):
                    # Add the section name as the task name
                    task_data: dict[str, Any] = {**section_data, "name": section_name}
                    tasks_dict[section_name] = TaskConfig(**task_data)

            config = TasksConfig(tasks=tasks_dict)
            logger.info(
                f"Loaded {len(config.tasks)} tasks "
                f"({len(config.get_enabled_tasks())} enabled)"
            )

            return config

        except ParseError as e:
            logger.error("Invalid tasks.toml, cannot load tasks")
            logger.error(str(e))
            return TasksConfig(tasks={})
        except ValidationError as e:
            logger.error("Invalid task configuration in tasks.toml")
            logger.error(str(e))
            return TasksConfig(tasks={})

    def save_tasks(self, tasks_config: TasksConfig, tasks_file: Path | None = None) -> None:
        """
        Save task configurations to TOML file.

        Patches each task's section in place against the existing document
        (or the bundled config file, if this is the first save).

        Args:
            tasks_config: TasksConfig object to save
            tasks_file: Path to tasks.toml
        """
        tasks_path = tasks_file or self.config_dir / "tasks.toml"
        doc = _load_document(tasks_path, defaults.build_tasks_toml)

        for task_name, task in tasks_config.tasks.items():
            task_data: dict[str, Any] = task.model_dump(by_alias=True, exclude={"name"})
            if task_name not in doc or not isinstance(doc[task_name], dict):
                doc[task_name] = table()
            _patch_document(doc[task_name], task_data)

        logger.info(f"Saving tasks to: {tasks_path}")
        tasks_path.write_text(dumps(doc))

    def load_ignored_services(
        self, services_file: Path | None = None
    ) -> IgnoredServicesConfig:
        """
        Load ignored services configuration.

        Args:
            services_file: Path to ignored-services.toml

        Returns:
            IgnoredServicesConfig object with the ignored services loaded from the file
        """
        services_path = services_file or self.config_dir / "ignored-services.toml"

        if not services_path.exists():
            logger.warning(f"Ignored services file not found: {services_path}")
            return IgnoredServicesConfig(services=[])

        logger.info(f"Loading ignored services from: {services_path}")

        try:
            doc = parse(services_path.read_text())
            if not doc:
                logger.warning("Ignored services file is empty, ignoring no services")
                return IgnoredServicesConfig(services=[])

            # Expected format: services = ["service1", "service2"]
            config = IgnoredServicesConfig(**doc)
            logger.info(f"Loaded {len(config.services)} ignored services")

            return config

        except ParseError as e:
            logger.error("Invalid ignored-services.toml, ignoring no services")
            logger.error(str(e))
            return IgnoredServicesConfig(services=[])
        except ValidationError as e:
            logger.error(
                "Invalid service structure in ignored-services.toml, ignoring no services"
            )
            logger.error(str(e))
            return IgnoredServicesConfig(services=[])

    def save_ignored_services(
        self, config: IgnoredServicesConfig, services_file: Path | None = None
    ) -> None:
        """
        Save ignored services configuration to TOML file.

        Args:
            config: IgnoredServicesConfig object to save
            services_file: Path to ignored-services.toml
        """
        services_path = services_file or self.config_dir / "ignored-services.toml"
        doc = _load_document(services_path, defaults.build_ignored_services_toml)

        _patch_document(doc, config.model_dump())

        logger.info(f"Saving ignored services to: {services_path}")
        services_path.write_text(dumps(doc))

    def load_settings(self, settings_file: Path | None = None) -> AppSettings:
        """
        Load application settings.

        Args:
            settings_file: Path to settings.toml (optional, uses defaults if not found)

        Returns:
            AppSettings object
        """

        settings_path = settings_file or self.config_dir / "settings.toml"

        # Load default settings if no settings.toml file exists
        if not settings_path.exists():
            logger.info("Settings file not found, using defaults")
            self._settings = self.load_default_settings()
            return self._settings

        logger.info(f"Loading settings from: {settings_path}")

        try:
            doc = parse(settings_path.read_text())

            # Load default settings if the file is empty
            if not doc:
                logger.warning("Settings file is empty, using defaults")
                self._settings = self.load_default_settings()
                return self._settings

            settings_data: dict[str, Any] = {"user": self.user}

            # Copy global settings
            for key in [
                "log_level",
                "log_retention_days",
                "require_confirmation",
                "dry_run",
            ]:
                if key in doc:
                    settings_data[key] = doc[key]

            # Load mirrorlist settings if present
            if "mirrorlist" in doc:
                settings_data["mirrorlist"] = MirrorlistSettings(**doc["mirrorlist"])

            # Load maintenance check settings if present
            if "maintenance_check" in doc:
                settings_data["maintenance_check"] = MaintenanceCheckSettings(
                    **doc["maintenance_check"]
                )

            settings = AppSettings(**settings_data)
            self._settings = settings
            settings.ensure_directories()

        # Load default settings if the file is invalid
        except ParseError as e:
            logger.error("Invalid settings.toml")
            logger.error(str(e))
            logger.warning("Using default settings")
            self._settings = self.load_default_settings()
        except ValidationError as e:
            logger.error("Invalid section in settings.toml")
            logger.error(str(e))
            logger.warning("Using default settings")
            self._settings = self.load_default_settings()

        return self._settings

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
        data: dict[str, Any] = settings.model_dump(
            exclude={"user"}, exclude_computed_fields=True
        )

        doc = _load_document(settings_path, defaults.build_settings_toml)
        _patch_document(doc, data)
        logger.info(f"Saving settings to: {settings_path}")

        settings_path.write_text(dumps(doc))

    def load_state(self, state_file: Path | None = None) -> AppState:
        """
        Load application state from JSON file.

        Args:
            state_file: Path to state.json (uses settings default if None)

        Returns:
            AppState object
        """
        state_path = state_file or self._settings.state_file

        if not state_path.exists():
            logger.info("State file not found, creating new state")
            return AppState()

        logger.info(f"Loading state from: {state_path}")

        try:
            with open(state_path) as f:
                data = json.load(f)
            if not data:
                logger.warning("State file is empty, starting with fresh state")
                return AppState()
            return AppState(**data)
        except json.JSONDecodeError as e:
            logger.error(str(e))
            logger.warning("Corrupt state file, starting with fresh state")
            return AppState()
        except ValidationError as e:
            logger.error(str(e))
            logger.warning("Invalid state file structure, starting with fresh state")
            return AppState()

    def save_state(self, state: AppState, state_file: Path | None = None) -> None:
        """
        Save application state to JSON file.

        Args:
            state: AppState object to save
            state_file: Path to state.json
        """
        state_path = state_file or self._settings.state_file
        state_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Saving state to: {state_path}")

        # Use model_dump with mode='json' to handle datetime serialization
        data = state.model_dump(mode="json")

        with open(state_path, "w") as f:
            json.dump(data, f, indent=4)


def create_default_config_files(
    config_dir: Path, force: bool = False
) -> tuple[list[Path], list[Path]]:
    """
    Create default configuration files for any that don't already exist.

    This is a helper function to bootstrap a new installation, or to fill
    in whatever's missing from a partially-configured one.

    Args:
        config_dir: Directory to create config files in
        force: Whether to overwrite existing files (default: False - only
            fills in what's missing, never touches customized files)

    Returns:
        Tuple of (created_files, skipped_files). skipped_files are those
        that already existed and force was False.
    """

    config_dir.mkdir(parents=True, exist_ok=True)

    builders: dict[str, Callable[[], TOMLDocument]] = {
        "settings.toml": defaults.build_settings_toml,
        "tasks.toml": defaults.build_tasks_toml,
        "ignored-services.toml": defaults.build_ignored_services_toml,
    }

    created: list[Path] = []
    skipped: list[Path] = []

    for filename, build in builders.items():
        target_path = config_dir / filename

        if target_path.exists() and not force:
            skipped.append(target_path)
            continue

        target_path.write_text(dumps(build()))
        created.append(target_path)

    return created, skipped
