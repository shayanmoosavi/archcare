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

## Where to go next

<div class="grid cards" markdown>

- :material-ruler-square-compass:{ .lg .middle } **Architecture**

    ***

    Why Archcare is layered the way it is: the dependency rules, the task
    execution lifecycle, and the ports and registry that keep the core
    frontend-agnostic.

    [:simple-blueprint: Explore the design](architecture/index.md){ .md-button .md-button--primary }

- :material-book-outline:{ .lg .middle } **Guides**

    ***

    Task-oriented walkthroughs: add a new maintenance task end to end, or set
    up a development environment and contribute.

    [:material-tools: Start building](guides/index.md){ .md-button .md-button--primary }

- :material-book-open-page-variant:{ .lg .middle } **Reference**

    ***

    Exhaustive, lookup-friendly material: every CLI command and option, every
    configuration-file key, and the auto-generated API documentation.

    [:material-text-search: Look it up](reference/index.md){ .md-button .md-button--primary }

</div>

---

## Project status

Archcare is under active development. Current work and planned tasks are
tracked in the
[roadmap](https://github.com/shayanmoosavi/archcare#roadmap) — including a
planned PySide6/QML GUI frontend that reuses the documented core
unmodified.
