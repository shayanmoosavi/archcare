"""Factory functions for default TOML documents for archcare's config files.

Uses tomlkit to build documents programmatically, preserving comments and
structure.
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
    """Return the default tasks.toml document."""
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
    doc = document()
    doc.add(comment("Services to ignore in failed-services check"))
    doc.add("services", ["systemd-networkd-wait-online.service"])
    return doc
