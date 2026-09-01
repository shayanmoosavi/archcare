# Archcare Documentation

**Archcare** is a system maintenance CLI for Arch Linux — it checks for failed
systemd services, runs disk/memory/CPU/filesystem health checks, keeps your
pacman mirrorlist fresh with automatic backup and rollback, and tracks which
maintenance tasks are due, on demand or fully unattended via systemd timers.

!!! tip "Looking to install or use Archcare?"

    The [README](https://github.com/shayanmoosavi/archcare#readme) covers
    installation, quick start, command usage, and configuration examples.
    This site is the technical companion: architecture, design decisions,
    extension guides, and exhaustive reference material.

---

## Documentation map

<div class="grid cards" markdown>

- :material-code-tags:{ .lg .middle } **API reference**

    ***

    Auto-generated, cross-referenced API documentation for every module,
    class, and function — built from the source docstrings.

    [:material-book-open-page-variant: Read the docs](autoapi/archcare/index.md){ .md-button .md-button--primary }

- :material-console:{ .lg .middle } **CLI reference**

    ***

    Every command, subcommand, and option — including exit-code behavior.

    [:material-magnify: Browse commands](reference/cli.md){ .md-button .md-button--primary }

- :material-ruler-square-compass:{ .lg .middle } **Architecture overview**

    ***

    The layered design, the dependency rules that hold it together, and the
    philosophy behind ports, registries, and typed results.

    [:material-cube-scan: Read the overview](architecture/overview.md){ .md-button .md-button--primary }

- :material-play-circle:{ .lg .middle } **Task execution lifecycle**

    ***

    From CLI command to state file: the full run flow, the `BaseTask`
    contract, and how task state is tracked and updated.

    [:material-map-marker-path: Walk the lifecycle](architecture/task-lifecycle.md){ .md-button .md-button--primary }

- :material-puzzle:{ .lg .middle } **Registry, ports & extensibility**

    ***

    How `TaskRegistry` wires everything together and how the port protocols
    keep the core frontend-agnostic.

    [:material-compass: Explore the seams](architecture/registry-and-ports.md){ .md-button .md-button--primary }

- :material-database-cog:{ .lg .middle } **Configuration & state**

    ***

    The Pydantic models behind `tasks.toml`, `settings.toml`, and
    `state.json` — and how they are loaded, validated, and persisted.

    [:material-application-braces-outline: See the models](architecture/configuration.md){ .md-button .md-button--primary }

- :material-plus-circle:{ .lg .middle } **Adding a new task**

    ***

    A complete, step-by-step guide to implementing, registering, formatting,
    and testing a new maintenance task.

    [:material-book-outline: Follow the guide](guides/adding-a-task.md){ .md-button .md-button--primary }

- :material-account-group:{ .lg .middle } **Contributing**

    ***

    Development setup, the testing philosophy, linting and type-checking
    pipeline, and release conventions.

    [:fontawesome-regular-handshake: Start contributing](guides/contributing.md){ .md-button .md-button--primary }

- :material-file-cog:{ .lg .middle } **Configuration files reference**

    ***

    Every key of every configuration file, with types, defaults, and
    semantics in one place.

    [:material-text-search: Look up a key](reference/configuration-files.md){ .md-button .md-button--primary }

</div>

---

## Project status

Archcare is under active development. Current work and planned tasks are
tracked in the
[roadmap](https://github.com/shayanmoosavi/archcare#roadmap) — including a
planned PySide6/QML GUI frontend that reuses the documented core
unmodified.
