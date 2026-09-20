# CLI reference

This page is the complete inventory of Archcare's command-line interface: every command,
option, default, and exit code, as of the current release. For how a command's work is
carried out internally, see [Task lifecycle](../architecture/task-lifecycle.md); for the
underlying Python API, see the [API reference](../autoapi/archcare/index.md).

!!! tip

    Everything below is also available offline via `archcare --help` (and per group,
    e.g. `archcare task run --help`). The help text is declared in `help=` parameters,
    deliberately separate from the API docstrings — see
    [Documentation conventions](../guides/contributing.md#documentation-conventions).

## Command tree

```text
archcare [--devel]
├── task                        Run and manage maintenance tasks
│   ├── run <task_name>         [--force/-f] [--verbose/-v]
│   ├── status [task_name]      [--due]
│   └── list                    [--type/-t automated|manual]
├── setup                       One-time bootstrapping
│   ├── config
│   └── timers                  [--enable/--no-enable] [--dry-run]
├── logs [task_name]            [--lines/-n N]
└── debug
    └── test-notification       [--severity/-s critical|warning|info]
```

## Global options

| Option    | Description                                                                                      |
| --------- | ------------------------------------------------------------------------------------------------ |
| `--devel` | Enable verbose console output (development mode). Processed eagerly, before any subcommand runs. |

## `archcare task`

### `task run`

Run a specific maintenance task.

```bash
archcare task run failed-services
archcare task run system-update --force
```

| Argument / option | Description                    | Default      |
| ----------------- | ------------------------------ | ------------ |
| `task_name`       | Name of the task to run        | **required** |
| `--force`, `-f`   | Run unconditionally            | off          |
| `--verbose`, `-v` | Show detailed execution output | off          |

### `task status`

Show status and schedule for tasks.

```bash
archcare task status                    # All tasks
archcare task status failed-services    # Specific task
archcare task status --due              # Only due tasks
```

| Argument / option | Description                                             | Default |
| ----------------- | ------------------------------------------------------- | ------- |
| `task_name`       | Specific task to check; omit for all tasks              | _       |
| `--due`           | Show only due tasks (ignored when `task_name` is given) | off     |

### `task list`

List all available and enabled tasks.

```bash
archcare task list                # Enabled tasks
archcare task list --type manual  # Manual tasks
```

| Argument / option    | Description                             | Default |
| -------------------- | --------------------------------------- | ------- |
| `--type`, `-t <str>` | Filter by type: `automated` or `manual` | _       |

## `archcare setup`

### `setup config`

Initialize Archcare's configuration files — writes the default
`tasks.toml`, `settings.toml`, and `ignored-services.toml` to `~/.config/archcare/`.
If any file already exists, Archcare prompts before overwriting. Takes no options.

### `setup timers`

Install the systemd template units (`archcare@.service`, `archcare@.timer`) into
`/etc/systemd/system/`, reload the daemon, and optionally enable and start one timer
per automated task. Must run via `sudo` — the target user is resolved from `SUDO_USER`.

```bash
archcare setup timers --dry-run
archcare setup timers
```

| Argument / option          | Description                                                | Default |
| -------------------------- | ---------------------------------------------------------- | ------- |
| `--enable` / `--no-enable` | Enable and start the per-task timers after installation    | enable  |
| `--dry-run`                | Show what would be done without touching disk or systemctl | off     |

## `archcare logs`

Show logs for Archcare or a specific task. A single command with an optional
argument: bare `archcare logs` tails the main `archcare.log`;
`archcare logs <task_name>` tails that task's `tasks/<task_name>.log`.

```bash
archcare logs                    # Main logs
archcare logs failed-services    # Task-specific logs
```

| Argument / option     | Description                      | Default  |
| --------------------- | -------------------------------- | -------- |
| `task_name`           | Task to show logs for            | main log |
| `--lines`, `-n <int>` | Number of trailing lines to show | 50       |

Log files live under `~/.local/state/archcare/logs/`.

## `archcare debug`

### `debug test-notification`

Send a test desktop notification to verify the notification system (requires
`notify-send`, i.e. libnotify).

```bash
archcare debug test-notification
archcare debug test-notification --severity critical
```

| Argument / option        | Description                                             | Default   |
| ------------------------ | ------------------------------------------------------- | --------- |
| `--severity`, `-s <str>` | Notification severity: `critical`, `warning`, or `info` | `warning` |

## Exit codes

!!! note "Writing scripts?"

    Every command exits `0` on success and `1` on any handled failure, so plain
    exit-code checks are reliable. `archcare task run` additionally exits `0` for
    `partial` and `skipped` outcomes — a skip is not a failure. Pair `run` with
    `--force` in scripts to bypass the due-date check, and `setup timers --dry-run`
    to preview changes non-destructively.

| Command                     | Exit 0                       | Exit 1                                                                |
| --------------------------- | ---------------------------- | --------------------------------------------------------------------- |
| `task run`                  | success, partial, or skipped | failure, unknown task, invalid/empty `tasks.toml`, user abort         |
| `task status` / `task list` | status rendered              | invalid/empty `tasks.toml`, unknown task, invalid `--type` value      |
| `setup config`              | files written                | write failure (a declined overwrite skips files, exit 0)              |
| `setup timers`              | installed (or dry-run shown) | not running as root, `SUDO_USER` unresolvable, systemd reload failure |
| `logs`                      | log shown                    | log file does not exist                                               |
| `debug test-notification`   | notification sent            | invalid severity, libnotify unavailable, send failure                 |

On any invocation against an uninitialized configuration, Archcare exits `1` with a
"Run `archcare setup config`" hint.

## Environment variables

| Variable        | Purpose                                                            |
| --------------- | ------------------------------------------------------------------ |
| `ARCHCARE_USER` | Override the target user (e.g. for systemd timers running as root) |
| `SUDO_USER`     | Original user when running via sudo; consumed by `setup timers`    |

## Related pages

- [Task lifecycle](../architecture/task-lifecycle.md) — what happens when a command runs
- [Configuration files reference](configuration-files.md) — every key behind these commands
- [CLI module (autoapi)](../autoapi/archcare/cli/index.md) — the implementing Python code
