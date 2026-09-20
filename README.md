# Archcare

A system maintenance CLI for Arch Linux — checks for failed services, runs health checks, keeps
your mirrorlist fresh, and tracks which maintenance tasks are due, all from one command.

> [!NOTE]
> The [documentation site](https://shayanmoosavi.github.io/archcare/) holds architecture
> details, contributing guides, and exhaustive CLI/config reference. For installation and
> quick-start steps, continue below.

## Why this exists

Archcare automates the handful of maintenance chores every Arch install eventually needs
(failed-unit checks, mirrorlist refreshes, disk/memory/CPU health checks) and tracks their schedule
so nothing quietly falls behind. It aims to be a user-friendly tool that makes maintenance easy,
painless, and reliable. If you're reading the code, the [Architecture](#architecture) section below
is for you.

## What Archcare touches on your system

Before running any maintenance tool, it's fair to ask what it changes. Archcare keeps to a small,
well-defined footprint:

- **Files it writes** — its own configuration under `~/.config/archcare/` and run state under
  `~/.local/state/archcare/`. Nothing else on disk is modified outside the explicit task actions
  below.
- **Where it needs sudo** — installing systemd timers (`archcare setup timers`) and replacing
  `/etc/pacman.d/mirrorlist` during a mirrorlist update.
- **Safety rails** — `archcare setup config` never overwrites existing configuration files, and
  mirrorlist updates create a backup first, rolling back automatically if `reflector` fails.

## Features

- **`failed-services`** — lists failed systemd units, with descriptions, status, and recent logs
  for each; supports an ignore-list for known-flaky units
- **`health-check`** — disk, memory, CPU, filesystem, and pacman-database health in one pass
- **`mirrorlist-update`** — refreshes `/etc/pacman.d/mirrorlist` via `reflector`, with automatic
  backup and rollback on failure
- **`maintenance-check`** — the scheduler-aware "what's due" task; reports overdue/at-risk
  maintenance across all other tasks by severity
- Per-task scheduling with configurable frequency, tracked run history, and a `task status` view
  showing what's due and what's overdue
- Optional desktop notifications on task completion
- Systemd timer integration for fully automated, unattended runs
- Verbose, per-task-formatted terminal output for every task result

Per-command options and example output for every task are in the
[CLI reference](https://shayanmoosavi.github.io/archcare/reference/cli/).

## Requirements

- systemd (already installed in most Arch installs)
- reflector — needed by the `mirrorlist-update` task

Optional dependencies, needed only for specific features:

- libnotify (`sudo pacman -S libnotify`) — desktop notifications
- gpg — verifying release signatures during installation (already present on most systems)

## Installation

### 1. Install reflector

```bash
sudo pacman -S reflector
```

### 2. Download the latest release

Simply download it from [here](https://github.com/shayanmoosavi/archcare/releases/latest).

### 3. Extract the archive

Either extract it with your favorite archive manager provided by your desktop (such as Xarchiever
or Ark), or via the terminal:

```bash
# Go to Downloads directory
cd ~/Downloads

# Extract the archive
tar -xf archcare-<VERSION>-linux-x86_64.tar.gz
```

where `<VERSION>` is the current downloaded version.

### 4. Verify the checksum and signature (optional)

The extracted archive contains 4 files — executable, checksum, signature, and build info
(for developers and debugging purposes).

You can verify the file integrity by validating its sha256 checksum:

```bash
sha256sum -c archcare.sha256
```

The output should be:

```text
archcare: OK
```

The file containing the checksum (The one with `.sha256` extension) is also GPG-signed (The file
with `.asc` extension is the signature). Verify the signature by entering this command:

```bash
gpg --verify archcare.sha256.asc
```

The output should contain this line:

```text
gpg: Good signature from "Shayan Moosavi (Github signing key) <moosavi.shayan@gmail.com>" [ultimate]
```

Once you've verified the authenticity of the software, you can delete the other files.

### 5. Install to `~/.local/bin`

If this path isn't in your `PATH`, add this line to your `~/.bashrc` (or `~/.zshrc` if your shell
is zsh):

```bash
export PATH="$PATH:$HOME/.local/bin"
```

Then source it (`source ~/.bashrc` or `source ~/.zshrc`) or close and re-open the terminal for
changes to take effect.

Install the executable to `~/.local/bin`:

```bash
install -D -m 755 archcare ~/.local/bin
```

## Uninstall

If you want to remove archcare entirely, three parts need cleanup:

- **Binary**: `rm ~/.local/bin/archcare`
- **Configuration**: `rm -rf ~/.config/archcare/` (removes `tasks.toml`, `settings.toml`,
  `ignored-services.toml`, state)
- **Systemd timers**: there is no uninstall command yet; stop and remove manually:
    ```bash
    systemctl --user stop archcare@*
    systemctl --user disable archcare@*
    sudo rm /etc/systemd/system/archcare@*
    sudo systemctl daemon-reload
    ```

## Quick start

A step-by-step walkthrough — what each step does and what to check along the way — is in the
[Getting started guide](https://shayanmoosavi.github.io/archcare/guides/getting-started/). The
short version:

```bash
# CLI reference
archcare --help

# Install shell completions
archcare --install-completion

# 1. Create default config files (first-time setup; non-destructive, safe to re-run)
archcare setup config

# 2. Review the generated configs and tune schedules to taste:
#    ~/.config/archcare/tasks.toml, settings.toml, ignored-services.toml

# 3. Run a task manually — no timers needed to try it out
archcare task run failed-services --verbose

# 4. See what's registered, what's due, and what's overdue
archcare task list
archcare task status --due

# 5. Only once you're happy with the results: automate it (needs sudo)
archcare setup timers
```

## Usage

Commands are grouped by area; run `archcare --help` or `archcare <group> --help` for the full,
always-up-to-date reference. The summary below covers the common cases. Every command, option,
flag, and exit code is documented in the
[CLI reference](https://shayanmoosavi.github.io/archcare/reference/cli/).

### `task` — run and inspect maintenance tasks

```bash
archcare task run <task-name> [--force] [--verbose]
archcare task status [<task-name>] [--due]
archcare task list [--type automated|manual]
```

- `--force` runs a task even if it isn't due yet
- `--verbose` shows the task's full structured details (not just the summary line) — e.g. every
  failed service's status and recent logs, or every maintenance item needing attention
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

## Troubleshooting

Three things commonly trip first-time users. Check them in order:

- **`archcare: command not found`** — `~/.local/bin` isn't on your `PATH`. Add
  `export PATH="$PATH:$HOME/.local/bin"` to your shell rc file, then re-open the terminal.
- **`reflector: command not found`** — the mirrorlist task needs it. Install it:
  `sudo pacman -S reflector`.
- **Timers aren't running** — verify with `systemctl --user list-timers --all` (user sessions)
  or `systemctl list-timers --all` (root/systemd). If you installed via `archcare setup timers`,
  check the target user is correct — timers run as the user set up, not whoever runs archcare.

## Desktop notifications

Archcare can send a desktop notification for due maintenance tasks. This needs `notify-send`, part
of `libnotify`; install it with `sudo pacman -S libnotify`. This is usually installed in most
standard Arch Linux installations.

To test that notifications work, run:

```bash
archcare debug test-notification --severity warning
```

Full command reference (options, exit codes, env vars):
[CLI reference](https://shayanmoosavi.github.io/archcare/reference/cli/).

## Configuration

Config lives under `~/.config/archcare/` (or the target user's home when run via a systemd timer
as root — see [this page](https://shayanmoosavi.github.io/archcare/reference/configuration-files/))
for complete configuration options.

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

**`ignored-services.toml`** — systemd units to exclude from `failed-services`, e.g. units known
to fail harmlessly on your system:

```toml
services = ["known-flaky.service", "some-other-service.service"]
```

Entries must be valid systemd unit names (any recognized unit type, not just `.service` — the
failed-unit check itself isn't type-restricted).

## Architecture

> [!NOTE]
> This section is only an overview, to see the entire architecture decisions including the
> class relationships, task execution lifecycle, and more, see the
> [Architecture](https://shayanmoosavi.github.io/archcare/architecture) section of the
> documentation.

Archcare is organized in a layered architecture as illustrated below:

```
cli/        Typer commands, presenters, terminal rendering
services/   Business logic, orchestrates core + config for each command
tasks/      Task implementations inheriting from `BaseTask`
core/       Task execution, scheduling, task/formatter registry
config/     Pydantic models, TOML/JSON loading and persistence
utils/      subprocess wrappers, system/hardware queries, notifications
```

A few things worth knowing if you're extending it:

- **Dependency injection throughout.** `AppContext` builds a `TaskExecutor` once per invocation
  and threads it down through `ctx.obj`; nothing reaches for global state.
- **Ports for anything environment-specific.** `TaskInteraction` (confirm/ notify) and
  `TaskDetailFormatter` (render a task's details) are both duck-typed protocols defined in `core/`,
  with CLI-specific implementations living in `cli/`. This is what will let a future GUI frontend
  reuse `core/` and `config/` unmodified — it just supplies its own interaction and
  formatter implementations.
- **One static registry.** `TaskRegistry` (`core/task_registry.py`) maps each task name to both
  its execution class and its detail formatter class, providing the presenters and execution
  engine with what they need.
- **Typed task results.** `TaskResult[TDetails]` is generic over a per-task details dataclass
  (`FailedServicesDetails`, `HealthCheckDetails`, etc. — see `core/task_details.py`), so a
  task's result carries real, typed, attribute-accessed data end to end instead of a
  loosely-keyed dict.
- **A real exception hierarchy.** Every layer has its own domain exceptions rooted in a single
  shared `ArchcareError` (`archcare/exceptions.py`), with `core`/`config` exceptions that need
  to pass through Pydantic validators deliberately also subclassing `ValueError` where required.

## Development

Development uses [uv](https://docs.astral.sh/uv/) as the project management tool — on Arch Linux
(btw 😎), install it with `sudo pacman -S uv`. To get started:

```bash
uv sync --all-groups   # install dev dependencies
uv run pytest          # run the test suite
uv run ty check        # static type checking
```

Contributions should keep to the layering above — in particular, `core/` and `config/` should never
import from `cli/` or `services/`. The full workflow — environment setup, the layering rule, code
style, pre-commit hooks, documentation conventions, and commit/PR conventions — lives in the
[Contributing guide](https://shayanmoosavi.github.io/archcare/guides/contributing/), and new
maintenance tasks are covered step by step in the
[Adding a task guide](https://shayanmoosavi.github.io/archcare/guides/adding-a-task/).

## Testing

```bash
uv run pytest                        # full suite
uv run pytest tests/unit             # unit tests only
uv run pytest tests/integration      # integration tests only
```

Unit tests (`tests/unit/`) mirror `src/archcare/` 1:1; integration tests (`tests/integration/`)
drive the real CLI via Typer's `CliRunner` and mock only the OS/subprocess boundary and desktop
notifications. The
[testing philosophy](https://shayanmoosavi.github.io/archcare/guides/contributing/#testing-philosophy)
section of the Contributing guide explains the reasoning behind the split.

## Roadmap

- Implementing the rest of the tasks in the default `tasks.toml`:
    - [x] failed-services
    - [x] maintenance-check
    - [x] health-check
    - [x] mirrorlist-update
    - [ ] system-update
    - [ ] journal-cleanup
    - [ ] orphan-removal
    - [ ] btrfs-scrub
    - [ ] disk-space-review
    - [ ] cache-cleanup
- [ ] PySide6/QML GUI frontend, reusing `core/`/`config/` as-is via the port
      boundaries described in the
      [ports and registry docs](https://shayanmoosavi.github.io/archcare/architecture/registry-and-ports/)

## License

This project is licensed under the GNU General Public License v3.0. See [LICENSE](LICENSE)
for details.
