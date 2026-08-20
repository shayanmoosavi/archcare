"""
Configuration loader for Archcare.

Handles loading, parsing, and saving TOML/JSON configuration/state files into
Pydantic models. Manages the application's configuration lifecycle including
tasks, settings, ignored services, and runtime state.

Key responsibilities:
    - Load and validate `tasks.toml`, `settings.toml`, `ignored-services.toml`
    - Persist configuration changes back to disk preserving comments/formatting
    - Manage `state.json` for task scheduling (last run, next due, status)
    - Provide default configurations for first-time setup

See Also:
    - [archcare.config.models][]: Pydantic models for configuration
    - [archcare.config.defaults][]: Default TOML document builders
    - [archcare.core.scheduler][]: TaskScheduler that consumes persisted state
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
    Load a TOML document from `path`, or build a default if the file doesn't exist.

    This preserves comments and formatting in existing files by using `tomlkit.parse`
    instead of replacing the file entirely.

    Args:
        path (pathlib.Path): Path to the TOML file to load.
        default_builder (Callable[[], TOMLDocument]): Zero-argument callable that
            returns a default `TOMLDocument` when the file is missing.

    Returns:
        TOMLDocument: The parsed document, or a fresh default document.

    Examples:
        >>> from tomlkit import document
        >>> from pathlib import Path
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     p = Path(tmp) / "test.toml"
        ...     doc = _load_document(p, lambda: document())
        ...     isinstance(doc, TOMLDocument)
        True
    """
    if path.exists():
        return parse(path.read_text())
    return default_builder()


def _patch_document(doc: dict[str, Any], data: dict[str, Any]) -> None:
    """
    Recursively patch `doc` in place with values from `data`.

    Only leaf values that differ are updated, preserving TOML comments and
    formatting in unmodified sections. Nested dictionaries are recursed into.

    Args:
        doc (dict[str, Any]): The target document or table to modify (mutated).
        data (dict[str, Any]): The source data to apply.

    Examples:
        >>> from tomlkit import table
        >>> doc = table(); doc["a"] = 1
        >>> _patch_document(doc, {"a": 2, "b": {"c": 3}})
        >>> doc["a"]
        2
        >>> doc["b"]["c"]
        3
    """
    for key, value in data.items():
        if isinstance(value, dict):
            if key not in doc or not isinstance(doc[key], dict):
                doc[key] = table()
            _patch_document(doc[key], value)
        else:
            doc[key] = value


class ConfigLoader:
    """
    Loads and manages application configuration.

    Central configuration manager that handles reading, writing, and validating
    all configuration files. Uses `tomlkit` to preserve comments and formatting
    in TOML files, and standard `json` for state persistence.

    Resolves the configuration directory from `AppSettings` defaults if not
    explicitly provided. Creates the directory if it doesn't exist.

    Attributes:
        user (str | None): The target username for config/state file ownership.
        config_dir (pathlib.Path): Directory containing configuration files.
    """

    def __init__(self, user: str | None = None, config_dir: Path | None = None):
        """
        Initialize the configuration loader.

        Args:
            user (str | None): Target username. Used for file ownership when
                running as root via systemd. Defaults to current user.
            config_dir (pathlib.Path | None): Override the default config directory
                (`~/.config/archcare`). If `None`, derived from `AppSettings`.

        Raises:
            OSError: If the config directory cannot be created.

        See Also:
            - [AppSettings][]: Global application settings model
            - [AppState][]: Runtime state model
            - [create_default_config_files][]: Bootstrap helper for new installations
            - [AppSettings.config_dir][]: Default directory resolution
        """
        # Use default settings to get config_dir if not provided
        self.user = user
        self._settings: AppSettings = AppSettings(user=user)
        self.config_dir = config_dir or self._settings.config_dir
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def load_tasks(self, tasks_file: Path | None = None) -> TasksConfig:
        """
        Load task configurations from `tasks.toml`.

        Parses the TOML file into a `TasksConfig` containing `TaskConfig` models.
        Missing or invalid files return an empty config with errors logged.

        Args:
            tasks_file (pathlib.Path | None): Path to `tasks.toml`. Defaults to
                `config_dir / "tasks.toml"`.

        Returns:
            TasksConfig: Parsed task configurations. Empty if file missing/invalid.

        See Also:
            - [save_tasks][]: Persist task configurations
            - [TaskConfig][]: Individual task schema
            - [TasksConfig][]: Container for all tasks
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
                f"Loaded {len(config.tasks)} tasks ({len(config.get_enabled_tasks())} enabled)"
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
        Save task configurations to `tasks.toml`.

        Updates the existing TOML document in place using `_patch_document`,
        preserving comments and formatting. Creates the file from defaults if
        it doesn't exist.

        Args:
            tasks_config (TasksConfig): Task configurations to persist.
            tasks_file (pathlib.Path | None): Target path. Defaults to
                `config_dir / "tasks.toml"`.

        Raises:
            OSError: If the file cannot be written.

        See Also:
            [load_tasks][]: Load task configurations
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

    def load_ignored_services(self, services_file: Path | None = None) -> IgnoredServicesConfig:
        """
        Load ignored systemd services from `ignored-services.toml`.

        Expected TOML format:
        ```toml
        services = ["service1.service", "service2.service"]
        ```

        Args:
            services_file (pathlib.Path | None): Path to `ignored-services.toml`.
                Defaults to `config_dir / "ignored-services.toml"`.

        Returns:
            IgnoredServicesConfig: List of service unit names to exclude from
                failed-services checks. Empty if file missing/invalid.

        See Also:
            - [save_ignored_services][]: Persist ignored services list
            - [IgnoredServicesConfig][]: Schema for ignored services
            - [FailedServicesTask][archcare.tasks.failed_services.FailedServicesTask]:
                Consumer of this config
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
            logger.error("Invalid service structure in ignored-services.toml, ignoring no services")
            logger.error(str(e))
            return IgnoredServicesConfig(services=[])

    def save_ignored_services(
        self, config: IgnoredServicesConfig, services_file: Path | None = None
    ) -> None:
        """
        Save ignored services list to `ignored-services.toml`.

        Updates the existing TOML document in place, preserving formatting.
        Creates the file from defaults if it doesn't exist.

        Args:
            config (IgnoredServicesConfig): Ignored services to persist.
            services_file (pathlib.Path | None): Target path. Defaults to
                `config_dir / "ignored-services.toml"`.

        Raises:
            OSError: If the file cannot be written.

        See Also:
            [load_ignored_services][]: Load ignored services
        """
        services_path = services_file or self.config_dir / "ignored-services.toml"
        doc = _load_document(services_path, defaults.build_ignored_services_toml)

        _patch_document(doc, config.model_dump())

        logger.info(f"Saving ignored services to: {services_path}")
        services_path.write_text(dumps(doc))

    def load_settings(self, settings_file: Path | None = None) -> AppSettings:
        """
        Load application settings from `settings.toml`.

        Merges file-based settings with defaults. Handles missing/invalid files
        gracefully by falling back to `load_default_settings()`. Caches the
        result in `self._settings` for subsequent calls.

        Args:
            settings_file (pathlib.Path | None): Path to `settings.toml`. Defaults
                to `config_dir / "settings.toml"`.

        Returns:
            AppSettings: Merged settings (file + defaults)

        See Also:
            - [load_default_settings][]: Get default settings without file I/O
            - [save_settings][]: Persist settings
            - [AppSettings][]: Settings schema
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
        Create an `AppSettings` instance with all default values.

        Does not read from disk. Ensures required directories exist.

        Returns:
            AppSettings: Fresh settings instance with defaults applied.

        See Also:
            - [AppSettings][]: Default values defined in model
            - [load_settings][]: Load settings from file with fallback to defaults
        """
        settings = AppSettings(user=self.user)
        settings.ensure_directories()
        return settings

    def save_settings(self, settings: AppSettings, settings_file: Path | None = None) -> None:
        """
        Save application settings to `settings.toml`.

        Serializes `AppSettings` to TOML using `_patch_document` to preserve
        comments and formatting. Excludes the `user` field and computed fields.

        Args:
            settings (AppSettings): Settings to persist.
            settings_file (pathlib.Path | None): Target path. Defaults to
                `config_dir / "settings.toml"`.

        Raises:
            OSError: If the file cannot be written.

        See Also:
            [load_settings][]: Load settings from file
        """
        settings_path = settings_file or self.config_dir / "settings.toml"

        # Convert to dict and handle Path objects
        data: dict[str, Any] = settings.model_dump(exclude={"user"}, exclude_computed_fields=True)

        doc = _load_document(settings_path, defaults.build_settings_toml)
        _patch_document(doc, data)
        logger.info(f"Saving settings to: {settings_path}")

        settings_path.write_text(dumps(doc))

    def load_state(self, state_file: Path | None = None) -> AppState:
        """
        Load runtime state from `state.json`.

        State includes per-task last run times, next due dates, status, and errors.
        Missing or corrupt files return a fresh `AppState` with errors logged.

        Args:
            state_file (pathlib.Path | None): Path to `state.json`. Defaults to
                `self._settings.state_file` (typically `~/.local/state/archcare/state.json`).

        Returns:
            AppState: Parsed state. Fresh instance if file missing/invalid.

        See Also:
            - [save_state][]: Persist state
            - [AppState][]: State schema
            - [TaskState][]: Per-task state schema
            - [TaskScheduler][archcare.core.scheduler.TaskScheduler]: Consumer of persisted state
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
        Persist runtime state to `state.json`.

        Creates the parent directory if needed. Uses `model_dump(mode='json')`
        for proper datetime serialization.

        Args:
            state (AppState): State to persist.
            state_file (pathlib.Path | None): Target path. Defaults to
                `self._settings.state_file`.

        Raises:
            OSError: If the file cannot be written.

        See Also:
            [load_state][]: Load state from file
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
    Bootstrap default configuration files in `config_dir`.

    Creates `settings.toml`, `tasks.toml`, and `ignored-services.toml` from
    bundled defaults. By default, only creates missing files (never overwrites).

    Args:
        config_dir (pathlib.Path): Target directory. Created if it doesn't exist.
        force (bool): If True, overwrite existing files. Default False.

    Returns:
        (tuple[list[Path], list[Path]]): A tuple of `created_files` and `skipped_files`.
            `skipped_files` are those that already existed when `force=False`.

    Raises:
        OSError: If directory creation or file writes fail.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     created, skipped = create_default_config_files(Path(tmp))
        ...     len(created), len(skipped)
        (3, 0)

    See Also:
        - [build_settings_toml][archcare.config.defaults.build_settings_toml]:
            Default settings template
        - [build_tasks_toml][archcare.config.defaults.build_tasks_toml]:
            Default tasks template
        - [build_ignored_services_toml][archcare.config.defaults.build_ignored_services_toml]:
            Default ignored services template
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
