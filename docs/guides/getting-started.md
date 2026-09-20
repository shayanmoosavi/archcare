# Getting Started

**Audience:** first-time Archcare users. This page takes you from a fresh install to automated,
unattended maintenance in five steps. If you want to change or extend Archcare instead, see the
[guides overview](index.md).

## Before you begin

- An Arch Linux system running systemd
- [reflector](https://man.archlinux.org/man/reflector.1), needed by the `mirrorlist-update` task
- The Archcare binary, installed via the
  [README installation steps](https://github.com/shayanmoosavi/archcare#installation)

Two optional extras: `libnotify` for desktop notifications and `gpg` for verifying release
signatures — both are covered in the [README](https://github.com/shayanmoosavi/archcare#readme).

Confirm the install works:

```bash
archcare --help
```

If the shell can't find the command, `~/.local/bin` isn't on your `PATH` — the README's
[troubleshooting section](https://github.com/shayanmoosavi/archcare#troubleshooting) has the fix.

## Step 1: Create the configuration

```bash
archcare setup config
```

This creates three files under `~/.config/archcare/`:

| File                    | Controls                                                                                               |
| ----------------------- | ------------------------------------------------------------------------------------------------------ |
| `tasks.toml`            | Which tasks exist, their type (`automated` / `manual`), frequency in days, and whether they're enabled |
| `settings.toml`         | Global behavior: log level, mirrorlist parameters, maintenance-check thresholds and output             |
| `ignored-services.toml` | systemd units excluded from the failed-services check (known-flaky units, for example)                 |

Creation is **non-destructive**: existing files are left untouched, so re-running the command is
always safe. Run state (last-run times, next-due dates), logs, and report files are kept separately
under `~/.local/state/archcare/`.

## Step 2: Review the defaults

The generated defaults are sensible, but two knobs are worth turning early:

**Task frequencies** in `tasks.toml` — how many days may pass before a task counts as overdue:

```toml
[failed-services]
type = "manual"      # "manual": run on demand; "automated": gets a systemd timer
frequency = 30       # considered overdue after 30 days without a run
enabled = true
```

**Mirrorlist preferences** in `settings.toml` — which mirrors `reflector` selects from:

```toml
[mirrorlist]
country = "Germany"      # or a list of countries
protocol = "https"
sort = "rate"
number_of_mirrors = 5
```

Every key, its default, and its meaning are documented in the
[Configuration files reference](../reference/configuration-files.md).

## Step 3: Run your first task

```bash
archcare task run failed-services --verbose
```

No timers or root access needed. You'll get a result panel with the task's status, message, and
duration; `--verbose` adds the full structured details — here, every failed systemd unit with its
status and recent logs.

The other tasks work the same way: `health-check`, `mirrorlist-update`, and `maintenance-check`
(the scheduler-aware "what's due" report). All command and flag variants are in the
[CLI reference](../reference/cli.md).

!!! note "Task isn't due yet?"

    `archcare task run <task> --force` runs a task regardless of its schedule — useful for trying
    things out.

## Step 4: Check the schedule

```bash
archcare task status --due
```

Lists registered tasks with their type, frequency, and last-run status — and, with `--due`, only
the ones currently due or overdue. Scheduling is computed from each task's `frequency` and the
last-run time recorded in `~/.local/state/archcare/state.json`.

## Step 5: Automate with systemd timers

Once manual runs look right:

```bash
archcare setup timers
```

This needs `sudo`. It installs a systemd timer for every task marked `type = "automated"` in
`tasks.toml`, so maintenance runs unattended on its schedule. Verify with
`systemctl list-timers --all`.

!!! note "Timers and users"

    Timers run as the user they were set up for. When a timer runs Archcare as root, the
    configuration and state of the original target user are used (overridable with the
    `ARCHCARE_USER` environment variable) — see the
    [configuration reference](../reference/configuration-files.md) for details.

## Common first-run questions

- **Is it safe to re-run `archcare setup config`?** Yes — it never overwrites existing
  configuration files unless specifically told to do so by answering `y` to the prompt.
- **Everything shows as due on the first run** — expected. `task run` records completion times;
  from then on, the schedule applies.
- **No desktop notifications?** Test delivery with
  `archcare debug test-notification --severity warning`. If that fails, install `libnotify`.
- **Timers exist but never fire?** Check `systemctl list-timers --all` and the timer's target user —
  the README's
  [troubleshooting section](https://github.com/shayanmoosavi/archcare#troubleshooting) covers the
  common causes.

## Where to go next

<div class="grid cards" markdown>

- :material-book-open-page-variant:{ .lg .middle } **CLI reference**

    ***

    Every command, option, flag, and exit code.

    [:material-text-search: Look it up](../reference/cli.md){ .md-button .md-button--primary }

- :material-cog:{ .lg .middle } **Configuration files**

    ***

    Every key in `tasks.toml`, `settings.toml`, and `ignored-services.toml`.

    [:material-tune: Tune it](../reference/configuration-files.md){ .md-button .md-button--primary }

- :simple-blueprint:{ .lg .middle } **Architecture**

    ***

    How Archcare works under the hood: layers, task lifecycle, ports.

    [:material-compass: Explore](../architecture/index.md){ .md-button .md-button--primary }

</div>
