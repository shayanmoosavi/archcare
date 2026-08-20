"""
Default TOML document builders for archcare configuration files.

This module provides factory functions that generate the default configuration
documents (TOML) used when a user runs `archcare setup config` for the first time.
It uses `tomlkit` to build documents programmatically while preserving comments,
formatting, and structure so that generated configs are human-readable and
well-documented.

The generated files are:
    - `tasks.toml` - Defines all maintenance tasks with their type, frequency, and description
    - `settings.toml` - Global settings and per-task configuration (mirrorlist, maintenance_check)
    - `ignored-services.toml` - List of systemd units to exclude from `failed-services` check

Each builder returns a `tomlkit.TOMLDocument` that can be written directly to disk.
The documents include extensive inline comments explaining each field and valid values.

Key Components:
    - [build_tasks_toml][]: Creates `tasks.toml` with automated and manual task definitions
    - [build_settings_toml][]: Creates `settings.toml` with global and task-specific settings
    - [build_ignored_services_toml][]: Creates `ignored-services.toml` with default ignore list

Configuration Files:
    Generated files are written to `~/.config/archcare/` (or the target user's
    config directory when run via systemd timer as root).

Examples:
    >>> from archcare.config.defaults import build_tasks_toml
    >>> from tomlkit import dumps
    >>> doc = build_tasks_toml()
    >>> print(dumps(doc)[:596])
    # Archcare Maintenance Tasks Configuration
    # Format: Each [task-name] section defines a maintenance task
    #
    # Fields:
    #   type = "automated" | "manual"
    #   frequency = <number>  (days between runs)
    #   description = <description>
    #   enabled = true | false
    <BLANKLINE>
    # ============================================================================
    # AUTOMATED TASKS (run automatically via systemd timers)
    # ============================================================================
    <BLANKLINE>
    [maintenance-check]
    type = "automated"
    frequency = 1
    description = "Check for due system maintenance tasks"
    enabled = true
    <BLANKLINE>

See Also:
    - [ConfigLoader][]: Loads and saves these configurations
    - [TaskConfig][]: Task configuration model
    - [AppSettings][]: Application settings model
    - [create_default_config_files][]: Function that uses these builders
"""

from typing import Any

from tomlkit import TOMLDocument, boolean, comment, document, nl, table

from .models import AppSettings, TaskConfig, TaskType

_SECTION_DIVIDER = "=" * 76

_AUTOMATED_TASKS = (
    TaskConfig(
        name="maintenance-check",
        type=TaskType.AUTOMATED,
        frequency=1,
        description="Check for due system maintenance tasks",
        enabled=True,
    ),
    TaskConfig(
        name="mirrorlist-update",
        type=TaskType.AUTOMATED,
        frequency=7,
        description="Update pacman mirror list",
        enabled=True,
    ),
    TaskConfig(
        name="journal-cleanup",
        type=TaskType.AUTOMATED,
        frequency=30,
        description="Clean old systemd journal logs",
        enabled=True,
    ),
    TaskConfig(
        name="btrfs-scrub",
        type=TaskType.AUTOMATED,
        frequency=30,
        description="Verify Btrfs filesystem integrity",
        enabled=True,
    ),
)

_MANUAL_TASKS = (
    TaskConfig(
        name="system-update",
        type=TaskType.MANUAL,
        frequency=7,
        description="Update system packages and clean pacman cache",
        enabled=True,
    ),
    TaskConfig(
        name="orphan-removal",
        type=TaskType.MANUAL,
        frequency=30,
        description="Remove orphaned packages",
        enabled=True,
    ),
    TaskConfig(
        name="cache-cleanup",
        type=TaskType.MANUAL,
        frequency=30,
        description="Clean user cache directories (~/.cache)",
        enabled=True,
    ),
    TaskConfig(
        name="pacnew-review",
        type=TaskType.MANUAL,
        frequency=30,
        description="Review and merge .pacnew/.pacsave files",
        enabled=True,
    ),
    TaskConfig(
        name="failed-services",
        type=TaskType.MANUAL,
        frequency=30,
        description="Check for failed systemd services",
        enabled=True,
    ),
    TaskConfig(
        name="health-check",
        type=TaskType.MANUAL,
        frequency=30,
        description="Perform health checks on system components",
        enabled=True,
    ),
    TaskConfig(
        name="disk-space-review",
        type=TaskType.MANUAL,
        frequency=90,
        description="Review large files and disk space usage",
        enabled=True,
    ),
)


def build_tasks_toml() -> TOMLDocument:
    """
    Build the default `tasks.toml` document.

    Returns:
        TOMLDocument: The default tasks configuration document.

    See Also:
        - [ConfigLoader][]: Loads and saves these configurations
        - [create_default_config_files][]: Function that creates the default config files
    """
    doc = document()

    # Header
    doc.add(comment("Archcare Maintenance Tasks Configuration"))
    doc.add(comment("Format: Each [task-name] section defines a maintenance task"))
    doc.add(comment(""))
    doc.add(comment("Fields:"))
    doc.add(comment('  type = "automated" | "manual"'))
    doc.add(comment("  frequency = <number>  (days between runs)"))
    doc.add(comment("  description = <description>"))
    doc.add(comment("  enabled = true | false"))
    doc.add(nl())

    # Automated tasks
    doc.add(comment(_SECTION_DIVIDER))
    doc.add(comment("AUTOMATED TASKS (run automatically via systemd timers)"))
    doc.add(comment(_SECTION_DIVIDER))
    doc.add(nl())

    _add_tasks(doc, _AUTOMATED_TASKS)
    doc.add(nl())

    # Manual tasks
    doc.add(comment(_SECTION_DIVIDER))
    doc.add(comment("MANUAL TASKS (require user interaction)"))
    doc.add(comment(_SECTION_DIVIDER))
    doc.add(nl())

    _add_tasks(doc, _MANUAL_TASKS)

    return doc


def _add_tasks(doc: TOMLDocument, tasks: tuple[TaskConfig, ...]) -> None:
    for i, task in enumerate(tasks):
        task_section = table()
        task_section.update(task.model_dump(by_alias=True, exclude={"name"}))
        doc.append(task.name, task_section)
        if i < len(tasks) - 1:
            doc.add(nl())


def build_settings_toml() -> TOMLDocument:
    """
    Build the default `settings.toml` document.

    Returns:
        TOMLDocument: The default settings configuration document.

    See Also:
        - [ConfigLoader][]: Loads and saves these configurations
        - [create_default_config_files][]: Function that creates the default config files
    """
    data: dict[str, Any] = AppSettings().model_dump(exclude={"user"}, exclude_computed_fields=True)
    doc = document()

    doc.add(comment("Global Settings"))
    for key in ("log_level", "log_retention_days", "dry_run"):
        doc.add(key, data[key])
    doc.add(nl())

    doc.add(comment("Mirrorlist Update Settings"))
    mirrorlist_section = table()
    mirrorlist_section.update(data["mirrorlist"])
    doc.add("mirrorlist", mirrorlist_section)
    doc.add(nl())

    doc.add(comment("Maintenance Check Settings"))
    maintenance_section = table()
    maintenance_section.update(data["maintenance_check"])

    # Adding inline comments
    maintenance_section["output_mode"].comment('"terminal", "file", "both"')
    maintenance_section["notification_level"].comment('"critical", "warning", "info"')

    # IMPORTANT: require_acknowledgment needs to be a tomlkit.Bool, otherwise the
    # comment cannot be attached inline
    require_acknowledgment = boolean(maintenance_section["require_acknowledgment"])
    require_acknowledgment.comment("For critical issues")
    maintenance_section["require_acknowledgment"] = require_acknowledgment

    doc.add("maintenance_check", maintenance_section)

    return doc


def build_ignored_services_toml() -> TOMLDocument:
    """
    Build the default `ignored-services.toml` document.

    Returns:
        TOMLDocument: The default ignored services configuration document.

    See Also:
        - [ConfigLoader][]: Loads and saves these configurations
        - [create_default_config_files][]: Function that creates the default config files
    """
    doc = document()
    doc.add(comment("Services to ignore in failed-services check"))
    doc.add("services", ["systemd-networkd-wait-online.service"])
    return doc
