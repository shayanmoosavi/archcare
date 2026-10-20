# CLI reference

This page is the complete inventory of Archcare's command-line interface: every command,
option, default, and exit code, as of the current release. For how a command's work is
carried out internally, see [Task lifecycle](../architecture/task-lifecycle.md); for the
underlying Python API, see the [API reference](api/index.md).

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
│   ├── list                    [--type/-t automated|manual]
│   └── recover <task_name>     Show recovery commands for a task
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

### `task recover`

Show recovery commands for a specific task. Prints the recovery artifacts (left by the last run) and
the commands needed to restore the system state. The commands are displayed only — they are
**not executed**. A snapshot rollback or database restore is destructive and irreversible; the
decision to run them belongs to the user.

```bash
archcare task recover system-update
```

| Argument / option | Description                 | Default      |
| ----------------- | --------------------------- | ------------ |
| `task_name`       | Name of the task to recover | **required** |

!!! note

    A recovery record must exist from a previous run. If no record is found, the command exits `1`
    with a reason naming the task and its path
    (`No recovery record found for "system-update" at ...`). An unreadable record reports the same
    way.

    The `system-update` task writes a recovery record (snapshot ID, sync DB backup, package
    manifests) on every run. The `recover` command reads that record and prints, most-relevant
    first:

    - `snapper rollback <id>` — shown only when a pre-update snapshot was created, so a machine
        without `snapper` never gets a rollback command it cannot run
    - `bash /path/to/downgrade.sh` — the generated restore script. It *executes only the
        sync-database restore*, then prints the ArchWiki full-restore commands
        (`pacman -Qe | sudo pacman -S -`, `pacman -Qmq`) **commented out** for you to review and
        run — nothing beyond the database restore runs on its own
    - `ls /var/cache/pacman/pkg/` plus an example
        `sudo pacman -U /var/cache/pacman/pkg/[package-name].pkg.tar.zst` — the manual reinstall
        path for packages the restore commands cannot reach

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

!!! note "Desktop notifications from timer runs"

    The generated `archcare@.service` runs as **root**, and root has *no* session D-Bus:
    without help, `notify-send` fails with *“Cannot autolaunch D-Bus without X11 $DISPLAY”* —
    even on Wayland, because that fallback is X11-era. Two mechanisms keep delivery working:

    - The unit template declares the target user's session bus explicitly
      (`DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/<uid>/bus`, plus `XDG_RUNTIME_DIR`),
      resolved from the user record at install time.
    - A user session bus accepts connections only from its owning user — a D-Bus policy
      independent of X11 or systemd; root gets the auth handshake completed and then the
      connection closed (`Error sending data: Broken pipe`). `NotificationManager` therefore
      re-executes `notify-send` through `runuser(1)` as the target user whenever it runs as
      a systemd service (`ARCHCARE_USER` set), re-declaring the bus address explicitly because
      `sudo` and system units scrub the end-user environment.

    Two conditions must still hold for a notification to actually arrive:

    - `/run/user/<uid>` must exist when the timer fires. Keep the user manager alive across
      logouts with `sudo loginctl enable-linger <user>` so overnight runs can still notify.
      Without it, the send is skipped and an error is written to the task log — the task itself
      is never affected.
    - A notification daemon (`dunst`, `mako`, `swaync`, …) must be running inside that user
      session to display what the bus receives.

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
- [CLI module (API)](api/cli/index.md) — the implementing Python code
