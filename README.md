# archcare

A system maintenance CLI for Arch Linux — checks for failed services, runs
health checks, keeps your mirrorlist fresh, and tracks which maintenance
tasks are due, all from one command.

## Why this exists

archcare automates the handful of maintenance chores every Arch install
eventually needs (failed-unit checks, mirrorlist refreshes, disk/memory/CPU
health checks) and tracks their schedule so nothing quietly falls behind.
It aims to be a user-friendly tool that makes maintenance easy, painless,
and reliable. If you're reading the code, the [Architecture](#architecture) section
below is for you.

## Features

- **`failed-services`** — lists failed systemd units, with descriptions,
  status, and recent logs for each; supports an ignore-list for known-flaky
  units
- **`health-check`** — disk, memory, CPU, filesystem, and pacman-database
  health in one pass
- **`mirrorlist-update`** — refreshes `/etc/pacman.d/mirrorlist` via
  `reflector`, with automatic backup and rollback on failure
- **`maintenance-check`** — the scheduler-aware "what's due" task; reports
  overdue/at-risk maintenance across all other tasks by severity
- Per-task scheduling with configurable frequency, tracked run history, and
  a `task status` view showing what's due and what's overdue
- Optional desktop notifications on task completion
- Systemd timer integration for fully automated, unattended runs
- Verbose, per-task-formatted terminal output for every task result

## Installation

Requires Python 3.13+, [Poetry](https://python-poetry.org/), and (for the
tasks that need them) `systemd`, `reflector`, and `pacman` — all standard on
an Arch install.

```bash
git clone https://github.com/shayanmoosavi/archcare.git
cd archcare
poetry install
```

Reflector isn't installed by default on most systems:

```bash
sudo pacman -S reflector
```

## Quick start

```bash
# CLI reference
archcare --help

# First-time setup: creates ~/.config/archcare/{tasks,settings,ignored-services}.toml
archcare setup config

# See what's registered
archcare task list

# Run one task
archcare task run failed-services

# Check what's due
archcare task status
```

## Usage

Commands are grouped by area; run `archcare --help` or `archcare <group>
--help` for the full, always-up-to-date reference. The summary below covers
the common cases.

### `task` — run and inspect maintenance tasks

```bash
archcare task run <task-name> [--force] [--verbose]
archcare task status [<task-name>] [--due]
archcare task list [--type automated|manual]
```

- `--force` runs a task even if it isn't due yet
- `--verbose` shows the task's full structured details (not just the summary
  line) — e.g. every failed service's status and recent logs, or every
  maintenance item needing attention
- `--due` on `task status` shows only tasks that are currently due

```bash
$ archcare task run health-check --verbose

Running Task: health-check
──────────────────────────

╭──── Task Result: health-check ─────╮
│ Status: ✓ SUCCESS                  │
│ Message: All health checks passed  │
│ Duration: 35.62s                   │
│                                    │
│ Details:                           │
│                                    │
│ System Summary:                    │
│   Disk Usage: 28.1%                │
│   Memory Usage: 50.9%              │
│   CPU Usage: 4.1%                  │
│   Pacman Database: Healthy         │
│   Installed Package Files: Healthy │
│   System Uptime: 3 days, 3 hours   │
╰────────────────────────────────────╯
```

### `setup` — first-time and ongoing configuration

```bash
archcare setup config              # create/repair config files (non-destructive)
archcare setup timers              # install systemd timers for automated tasks (needs sudo)
```

### `debug` — diagnostics

```bash
archcare debug test-notification --severity warning   # test desktop notification delivery
```

### `logs`

```bash
archcare logs                      # view recent archcare log output
```

## Configuration

Config lives under `~/.config/archcare/` (or the target user's home when run
via a systemd timer as root — see [Architecture](#architecture)).

**`tasks.toml`** — defines every task's schedule and type:

```toml
[failed-services]
type = "manual"
frequency = 30
description = "Check for failed systemd services"
enabled = true

[maintenance-check]
type = "automated"
frequency = 1
description = "Check for due system maintenance tasks"
enabled = true
```

**`settings.toml`** — global and per-task behavior:

```toml
log_level = "INFO"
log_retention_days = 30
require_confirmation = true

[mirrorlist]
country = "Germany"
protocol = "https"
sort = "rate"
number_of_mirrors = 5

[maintenance_check]
critical_threshold_days = 7
warning_threshold_days = 0
output_mode = "terminal"
require_acknowledgment = true
```

**`ignored-services.toml`** — systemd units to exclude from
`failed-services`, e.g. units known to fail harmlessly on your system:

```toml
services = ["known-flaky.service", "getty@tty7.service"]
```

Entries must be valid systemd unit names (any recognized unit type, not
just `.service` — the failed-unit check itself isn't type-restricted).

## Architecture

archcare is organized in strict layers, each only depending on the ones
below it:

```
cli/        Typer commands, presenters, terminal rendering
services/   Business logic, orchestrates core + config for each command
core/       Task execution, scheduling, task/formatter registry
config/     Pydantic models, TOML/JSON loading and persistence
utils/      subprocess wrappers, system/hardware queries, notifications
```

A few things worth knowing if you're extending it:

- **Dependency injection throughout.** `AppContext` builds a `TaskExecutor`
  once per invocation and threads it down through `ctx.obj`; nothing reaches
  for global state.
- **Ports for anything environment-specific.** `TaskInteraction` (confirm/
  notify) and `TaskDetailFormatter` (render a task's details) are both
  duck-typed protocols defined in `core/`, with CLI-specific implementations
  living in `cli/`. This is what will let a future GUI frontend reuse `core/`
  and `config/` unmodified — it just supplies its own interaction and
  formatter implementations.
- **One static registry.** `TaskRegistry` (`core/task_registry.py`)
  maps each task name to both its execution class and its detail formatter
  class, providing the presenters and execution engine with what they need.
- **Typed task results.** `TaskResult[TDetails]` is generic over a per-task
  details dataclass (`FailedServicesDetails`, `HealthCheckDetails`, etc. —
  see `core/task_details.py`), so a task's result carries real, typed,
  attribute-accessed data end to end instead of a loosely-keyed dict.
- **A real exception hierarchy.** Every layer has its own domain exceptions
  rooted in a single shared `ArchcareError` (`archcare/exceptions.py`), with
  `core`/`config` exceptions that need to pass through Pydantic validators
  deliberately also subclassing `ValueError` where required.

## Testing

```bash
poetry run pytest                        # full suite
poetry run pytest tests/unit             # unit tests only
poetry run pytest tests/integration      # integration tests only
poetry run ty check                      # static type checking
```

The suite is split by intent, not just by directory:

- **Unit tests** (`tests/unit/`) mirror `src/archcare/` 1:1 and use mocks at
  precise boundaries — real Pydantic models over bare mocks wherever
  construction is cheap, `mocker.patch.object` over stacked `@patch`
  decorators, and specced mocks (`MagicMock(spec=X)`) to catch attribute
  typos.
- **Integration tests** (`tests/integration/`) invoke the real CLI via
  Typer's `CliRunner`, build a real `AppContext`, and do real file I/O under
  `tmp_path`. The _only_ things ever mocked are the actual OS/subprocess
  boundary (`utils/system.py`'s `run_command`/`run_command_with_sudo`) and
  desktop notifications. This combination has caught real bugs unit tests
  alone missed — see `git log` for a couple of examples where a mocked unit
  test passed while the real wiring was broken.

## Development

```bash
poetry install --with dev
poetry run pytest
poetry run ty check
```

Contributions should keep to the layering above — in particular, `core/`
and `config/` should never import from `cli/` or `services/`. If you're
adding a new task, look at `core/task_registry.py`'s `DEFAULT_TASK_REGISTRY`
and `core/task_details.py` for the pattern every existing task follows.

## Roadmap

- PySide6/QML GUI frontend, reusing `core/`/`config/` as-is via the port
  boundaries described above
- Implementing progress bars, spinners, etc., for long-running tasks.
- Implementing the rest of the tasks in the default `tasks.toml`

## License

This project is licensed under the GNU General Public License v3.0. See
[LICENSE](LICENSE) for details.
