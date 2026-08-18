# AGENTS.md - Archcare Project Reference

This document provides a comprehensive reference for working with the Archcare codebase. It covers architecture, key patterns, and practical guidance for common tasks.

---

## Project Overview

**Archcare** is a system maintenance CLI for Arch Linux that:

- Checks for failed systemd services (`failed-services`)
- Runs health checks (disk, memory, CPU, filesystem, pacman database) (`health-check`)
- Refreshes mirrorlist via `reflector` with backup/rollback (`mirrorlist-update`)
- Tracks maintenance task schedules and reports what's due (`maintenance-check`)

**Tech Stack**: Python 3.13+, Typer (CLI), Rich (terminal UI), Loguru (logging), Pydantic (config/validation), psutil (system metrics)

---

## Architecture (Layered)

```
cli/        → Typer commands, presenters, terminal rendering
services/   → Business logic, orchestrates core + config for each command
tasks/      → Task implementations inheriting from BaseTask
core/       → Task execution, scheduling, task/formatter registry
config/     → Pydantic models, TOML/JSON loading and persistence
utils/      → subprocess wrappers, system/hardware queries, notifications
```

### Key Architectural Principles

1. **Dependency Injection** - `AppContext` builds a `TaskExecutor` once per invocation and threads it down through `ctx.obj`; nothing reaches for global state.

2. **Ports for Environment-Specific Code** - `TaskInteraction` (confirm/notify) and `TaskDetailFormatter` (render task details) are duck-typed protocols defined in `core/`, with CLI implementations in `cli/`. This enables a future GUI to reuse `core/` and `config/` unmodified.

3. **Static Registry** - `TaskRegistry` (`core/task_registry.py`) maps each task name to its execution class and detail formatter class.

4. **Typed Task Results** - `TaskResult[TDetails]` is generic over a per-task details dataclass (`FailedServicesDetails`, `HealthCheckDetails`, etc. in `core/task_details.py`).

5. **Exception Hierarchy** - Every layer has its own domain exceptions rooted in `ArchcareError` (`archcare/exceptions.py`), with `core`/`config` exceptions that pass through Pydantic validators deliberately also subclassing `ValueError`.

---

## Directory Structure (Key Files)

### Core Layer (`src/archcare/core/`)

| File               | Purpose                                                                                                                                |
| ------------------ | -------------------------------------------------------------------------------------------------------------------------------------- |
| `executor.py`      | `TaskExecutor` - coordinates task instantiation, execution, state updates                                                              |
| `task_registry.py` | `TaskRegistry`, `TaskDescriptor` - static mapping of task name → (class, formatter)                                                    |
| `models.py`        | `TaskResult[TDetails]`, `TaskStep`, `IssueSeverity`, `MaintenanceIssue`, factory functions (`success`, `failed`, `skipped`, `partial`) |
| `task_details.py`  | Per-task detail dataclasses: `FailedServicesDetails`, `HealthCheckDetails`, `MaintenanceCheckDetails`, `MirrorlistUpdateDetails`       |
| `scheduler.py`     | `TaskScheduler` - determines if tasks are due based on frequency/last run                                                              |
| `formatter.py`     | `TaskDetailFormatter` protocol, `DefaultFormatter`                                                                                     |
| `interaction.py`   | `TaskInteraction` protocol, `NonInteractive` implementation                                                                            |
| `progress.py`      | `TaskProgress` protocol, `NoOpProgress`, `RichProgress`                                                                                |
| `notifications.py` | `NotificationManager` - desktop notifications via `notify-send`                                                                        |
| `exceptions.py`    | Core exception hierarchy                                                                                                               |

### Config Layer (`src/archcare/config/`)

| File          | Purpose                                                                                                                                                                                                                     |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `models.py`   | Pydantic models: `TaskConfig`, `TasksConfig`, `AppSettings`, `AppState`, `TaskState`, `MirrorlistSettings`, `MaintenanceCheckSettings`, `IgnoredServicesConfig`, enums (`TaskType`, `TaskStatus`, `SkipReason`, `LogLevel`) |
| `loader.py`   | `ConfigLoader` - loads/saves TOML (settings, tasks, ignored-services) and JSON (state)                                                                                                                                      |
| `defaults.py` | Default TOML document builders for initial config creation                                                                                                                                                                  |
| `logging.py`  | Logging setup with loguru                                                                                                                                                                                                   |

### Tasks Layer (`src/archcare/tasks/`)

| File                   | Purpose                                                                                                             |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `base.py`              | `BaseTask` - abstract base with `execute()`, `pre_check()`, `should_run()`, `post_execute()`, `rollback()`, `run()` |
| `failed_services.py`   | `FailedServicesTask` - checks systemd failed units                                                                  |
| `health_check.py`      | `HealthCheckTask` - disk, memory, CPU, filesystem, pacman checks                                                    |
| `mirrorlist_update.py` | `MirrorlistUpdateTask` - runs reflector with backup/rollback                                                        |
| `maintenance_check.py` | `MaintenanceCheckTask` - scheduler-aware "what's due" report                                                        |

### Services Layer (`src/archcare/services/`)

| File               | Purpose                                                                            |
| ------------------ | ---------------------------------------------------------------------------------- |
| `task_service.py`  | `TaskService` - high-level operations: `run_task`, `get_task_status`, `list_tasks` |
| `setup_service.py` | `SetupService` - config creation, systemd timer installation                       |
| `debug_service.py` | `DebugService` - notification testing                                              |
| `responses.py`     | Response dataclasses for service layer                                             |

### CLI Layer (`src/archcare/cli/`)

| File             | Purpose                                                                                        |
| ---------------- | ---------------------------------------------------------------------------------------------- |
| `app.py`         | Typer app, command groups, main callback                                                       |
| `context.py`     | `AppContext` - per-invocation context with lazy `ConfigLoader`, `TaskExecutor`, `TaskRegistry` |
| `commands/`      | Command implementations: `task.py`, `setup.py`, `logs.py`, `debug.py`                          |
| `presenters/`    | Terminal rendering: `TaskPresenter`, formatters for each task                                  |
| `interaction.py` | `CliInteraction` - implements `TaskInteraction` for CLI                                        |
| `progress.py`    | `RichProgress` - implements `TaskProgress` with Rich                                           |

### Utils Layer (`src/archcare/utils/`)

| File            | Purpose                                                                             |
| --------------- | ----------------------------------------------------------------------------------- |
| `system.py`     | `run_command`, `run_command_with_sudo` - subprocess wrappers (the ONLY OS boundary) |
| `hardware.py`   | Disk, memory, CPU queries via psutil                                                |
| `pacman.py`     | Pacman database/package health checks                                               |
| `mirrorlist.py` | Mirrorlist parsing, reflector invocation                                            |
| `user.py`       | `UserContext` - resolves ARCHCARE_USER/SUDO_USER, chown helpers                     |

---

## Key Patterns

### Adding a New Task

1. **Create detail dataclass** in `core/task_details.py`:

```python
@dataclass(frozen=True)
class MyTaskDetails:
    field1: str
    field2: int = 0
```

2. **Create task class** in `tasks/my_task.py` inheriting `BaseTask`:

```python
class MyTask(BaseTask):
    def pre_check(self) -> tuple[bool, str]:
        # Verify prerequisites (e.g., command exists)
        return True, ""

    def should_run(self) -> tuple[bool, str, SkipReason | None]:
        # Runtime decision - is there work to do?
        return True, "", None

    def execute(self) -> TaskResult[MyTaskDetails]:
        # Main logic
        return success("Done", details=MyTaskDetails(field1="value"))

    def post_execute(self, result: TaskResult) -> None:
        # Cleanup, notifications
        pass
```

3. **Create formatter** in `cli/presenters/` implementing `TaskDetailFormatter` protocol.

4. **Register in `cli/context.py`** `DEFAULT_TASK_REGISTRY`:

```python
TaskDescriptor("my-task", MyTask, MyTaskFormatter),
```

5. **Add default config** in `config/defaults.py` `build_tasks_toml()`.

### Task Execution Flow

```
User runs: archcare task run failed-services
                │
                ▼
Typer callback → AppContext (builds executor, registry, loader)
                │
                ▼
TaskService.run_task() → TaskExecutor.execute_task()
                │
                ▼
TaskExecutor._create_task() → FailedServicesTask(config, settings, ...)
                │
                ▼
BaseTask.run() → pre_check() → should_run() → execute() → post_execute()
                │
                ▼
TaskExecutor._update_state() → saves next_due to state.json
                │
                ▼
TaskPresenter.render_run() → terminal output
```

### Configuration Files

| File                    | Location                   | Purpose                                                               |
| ----------------------- | -------------------------- | --------------------------------------------------------------------- |
| `tasks.toml`            | `~/.config/archcare/`      | Task definitions: name, type, frequency, enabled, description         |
| `settings.toml`         | `~/.config/archcare/`      | Global + per-task settings (log level, mirrorlist params, thresholds) |
| `ignored-services.toml` | `~/.config/archcare/`      | List of systemd units to exclude from failed-services                 |
| `state.json`            | `~/.local/state/archcare/` | Last run timestamps, next due dates, status per task                  |

### State Management

- `AppState` holds `TaskState` per task: `last_run`, `next_due`, `status`, `error`, `skip_reason`
- `TaskExecutor._update_state()` called after every execution (success, failure, skip)
- Next due calculated: `datetime.now() + timedelta(days=frequency)` on success; preserved on skip/failure

---

## Testing

### Structure

```
tests/
├── unit/           # Mirrors src/archcare/ 1:1, mocks at precise boundaries
│   ├── config/
│   ├── core/
│   ├── services/
│   ├── tasks/
│   └── utils/
├── integration/    # Real CLI via CliRunner, real AppContext, real file I/O (tmp_path)
│   ├── cli/
│   └── tasks/
└── conftest.py
```

### Test Principles

- **Unit tests**: Real Pydantic models over bare mocks; `mocker.patch.object` over stacked `@patch`; specced mocks (`MagicMock(spec=X)`)
- **Integration tests**: Only mock `utils/system.py`'s `run_command`/`run_command_with_sudo` and desktop notifications
- Run: `uv run pytest`, `uv run pytest tests/unit`, `uv run pytest tests/integration`

---

## Development Commands

```bash
# Install deps (all groups)
uv sync --all-groups

# Run tests
uv run pytest                    # full suite
uv run pytest tests/unit         # unit only
uv run pytest tests/integration  # integration only

# Type checking
uv run ty check

# Linting
uv run ruff check
uv run ruff format

# Build script
scripts/build.sh
```

---

## Common Tasks Reference

### Run a task manually

```bash
archcare task run failed-services --force --verbose
```

### Check what's due

```bash
archcare task status --due
```

### List all tasks

```bash
archcare task list --type automated
```

### First-time setup

```bash
archcare setup config      # Creates config files
archcare setup timers      # Installs systemd timers (needs sudo)
```

### Debug notifications

```bash
archcare debug test-notification --severity warning
```

---

## Environment Variables

| Variable        | Purpose                                                      |
| --------------- | ------------------------------------------------------------ |
| `ARCHCARE_USER` | Override target user (for systemd timers running as root)    |
| `SUDO_USER`     | Original user when running via sudo (used by `setup timers`) |

---

## Error Handling Patterns

- **Config errors**: `ConfigNotInitializedError` → CLI catches, suggests `archcare setup config`
- **Task not found**: `TaskNotRegisteredError` (core) / `TaskNotFoundError` (services)
- **Validation errors**: Pydantic `ValidationError` caught in `ConfigLoader`, falls back to defaults
- **OS errors**: Wrapped in `utils/system.py` → `CommandError` with stdout/stderr/exit_code

---

## Ports (Protocols for Extensibility)

| Protocol              | Location              | CLI Implementation                  | Purpose               |
| --------------------- | --------------------- | ----------------------------------- | --------------------- |
| `TaskInteraction`     | `core/interaction.py` | `cli/interaction.py:CliInteraction` | confirm(), notify()   |
| `TaskDetailFormatter` | `core/formatter.py`   | `cli/presenters/*.py`               | render_task_details() |
| `TaskProgress`        | `core/progress.py`    | `cli/progress.py:RichProgress`      | advance(), stop()     |

A GUI frontend would implement these three protocols and supply them to `TaskExecutor`.

---

## Important Notes for Contributors

1. **Layering**: `core/` and `config/` must NEVER import from `cli/` or `services/`
2. **Single registry**: All task registration happens in `cli/context.py` `DEFAULT_TASK_REGISTRY`
3. **State file ownership**: When running as root via systemd, `TaskExecutor._update_state()` chowns state file to target user
4. **Logging**: Per-task log handlers added/removed in `BaseTask.run()` via `setup_task_logging()`
5. **Notifications**: `NotificationManager` lazily constructed (does `notify-send` availability check on init)
