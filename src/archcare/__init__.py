"""
Package root for Archcare.

Archcare is a system maintenance CLI for Arch Linux: it automates routine maintenance tasks such as
checking for failed systemd services, running system health checks, refreshing the pacman mirrorlist
via reflector (with backup/rollback), and additionally tracking maintenance task schedules —
runnable manually or as systemd timers.

Modules:
    cli: Typer commands, presenters, terminal rendering
    services: business logic facades returning response DTOs
    tasks: task implementations inheriting from [`BaseTask`][archcare.core.base_task.BaseTask]
    core: task execution, scheduling, registries, ports (protocols)
    config: Pydantic settings/state models, TOML/JSON persistence
    utils: subprocess wrappers and system queries (the only OS boundary)

See Also:
    - [`archcare.cli.app.main`][]: Console-script entry point
    - [`ArchcareError`][archcare.exceptions.ArchcareError]: Root of the exception hierarchy
"""
