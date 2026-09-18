# Configuration files reference

This page inventories every configuration key, its default, and its valid values.
For how loading, validation, and persistence actually work — the loader, the
fall-back-on-invalid behavior, and the state update cycle — see
[Configuration & state](../architecture/configuration.md).

| File                    | Location                   | Purpose                                          |
| ----------------------- | -------------------------- | ------------------------------------------------ |
| `tasks.toml`            | `~/.config/archcare/`      | Task definitions: name, type, frequency, enabled |
| `settings.toml`         | `~/.config/archcare/`      | Global settings and per-task configuration       |
| `ignored-services.toml` | `~/.config/archcare/`      | systemd units excluded from `failed-services`    |
| `state.json`            | `~/.local/state/archcare/` | Runtime state per task (managed by Archcare)     |

Logs (`logs/`) and maintenance-check reports (`reports/`) also live under
`~/.local/state/archcare/`. All of the above are created by `archcare setup config`
and first run.

## `tasks.toml`

Each `[task-name]` section defines one task:

```toml title="tasks.toml"
[health-check]
type = "automated"                              # "automated" | "manual"
frequency = 7                                   # days between runs (must be > 0)
description = "Perform health checks on system components"
enabled = true                                  # disabled tasks are skipped with reason "disabled"
```

The section name is the task's unique identifier, used in CLI commands
(`archcare task run health-check`) and as the key in `state.json`. Names may contain
alphanumeric characters, hyphens, and underscores.

### Default task inventory

`archcare setup config` generates eleven tasks:

| Task                | Type        | Frequency | Description                                   |
| ------------------- | ----------- | --------- | --------------------------------------------- |
| `maintenance-check` | `automated` | 1 day     | Check for due system maintenance tasks        |
| `mirrorlist-update` | `automated` | 7 days    | Update pacman mirror list                     |
| `journal-cleanup`   | `automated` | 30 days   | Clean old systemd journal logs                |
| `btrfs-scrub`       | `automated` | 30 days   | Verify Btrfs filesystem integrity             |
| `system-update`     | `manual`    | 7 days    | Update system packages and clean pacman cache |
| `orphan-removal`    | `manual`    | 30 days   | Remove orphaned packages                      |
| `cache-cleanup`     | `manual`    | 30 days   | Clean user cache directories (`~/.cache`)     |
| `pacnew-review`     | `manual`    | 30 days   | Review and merge `.pacnew`/`.pacsave` files   |
| `failed-services`   | `manual`    | 30 days   | Check for failed systemd services             |
| `health-check`      | `manual`    | 30 days   | Perform health checks on system components    |
| `disk-space-review` | `manual`    | 90 days   | Review large files and disk space usage       |

`automated` tasks run on schedule via systemd timers; `manual` tasks only run when
you invoke `archcare task run <name>` explicitly. To add your own task, see
[Adding a new task](../guides/adding-a-task.md).

## `settings.toml`

### Global settings

| Key                  | Default  | Valid values                                    |
| -------------------- | -------- | ----------------------------------------------- |
| `log_level`          | `"INFO"` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `log_retention_days` | `30`     | Days to retain rotated log files                |
| `dry_run`            | `false`  | Preview mode for task execution                 |

### `[mirrorlist]`

Settings for the `mirrorlist-update` task (consumed by `reflector`).

| Key                 | Default                      | Description                                 |
| ------------------- | ---------------------------- | ------------------------------------------- |
| `path`              | `"/etc/pacman.d/mirrorlist"` | Mirrorlist file to rewrite                  |
| `country`           | `"Germany"`                  | Country filter for mirror selection         |
| `protocol`          | `"https"`                    | Mirror protocol                             |
| `sort`              | `"rate"`                     | Mirror sort strategy                        |
| `latest`            | `20`                         | Consider the N most recently synced mirrors |
| `number_of_mirrors` | `5`                          | Number of mirrors to write                  |

### `[maintenance_check]`

Settings for the `maintenance-check` task's report and notifications.

| Key                       | Default      | Valid values / description                                |
| ------------------------- | ------------ | --------------------------------------------------------- |
| `critical_threshold_days` | `7`          | Overdue-by days that count as critical                    |
| `warning_threshold_days`  | `0`          | Overdue-by days that count as warning                     |
| `output_mode`             | `"terminal"` | `"terminal"`, `"file"`, or `"both"`                       |
| `show_notifications`      | `true`       | Send desktop notifications for due/critical tasks         |
| `notification_level`      | `"warning"`  | `"critical"`, `"warning"`, or `"info"`                    |
| `report_retention_days`   | `30`         | Days to keep generated reports (for `"file"` or `"both"`) |
| `require_acknowledgment`  | `true`       | Critical issues require explicit acknowledgment           |

!!! warning

    `warning_threshold_days` must be strictly less than `critical_threshold_days` —
    a configuration violating this falls back to defaults on load.

## `ignored-services.toml`

A single list of systemd units to exclude from the `failed-services` check —
for units that are known to fail sometimes:

```toml title="ignored-services.toml"
services = ["systemd-networkd-wait-online.service"]
```

## `state.json`

Managed entirely by Archcare — edit only with care (or while no run is in flight).
One entry per task tracks its schedule and last outcome:

| Field         | Type                              | Description                                                                                                                   |
| ------------- | --------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `last_run`    | <code>datetime &#124; null</code> | Timestamp of the most recent execution attempt                                                                                |
| `last_status` | <code>string &#124; null</code>   | Outcome of the most recent run, one of: `success`, `failure`, `skipped`, `partial`                                            |
| `next_due`    | <code>datetime &#124; null</code> | When the task should run next                                                                                                 |
| `run_count`   | `int`                             | Total executions (default `0`)                                                                                                |
| `last_error`  | <code>string &#124; null</code>   | Error message from the most recent failed run                                                                                 |
| `skip_reason` | <code>string &#124; null</code>   | Why the last run was skipped, one of: `no_work_needed`, `disabled`, `dependency_failed`, `user_cancelled`, `not_due`, `other` |

Scheduling rule: on a successful run, `next_due` becomes `last_run + frequency` days;
on a skip or failure it is preserved, so an overdue task stays overdue.

## Related pages

- [Configuration & state](../architecture/configuration.md) — loading, validation, persistence
- [CLI reference](cli.md) — the commands that read and write these files
- [Config module (API)](api/config/index.md) — the Pydantic models behind every key
