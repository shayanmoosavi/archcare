"""
Setup service - business logic for `setup config` and `setup timers`.

This module contains the two services behind archcare's first-run setup:

- [ConfigService][]: `setup config` — checks for existing TOML configuration files and writes
    bundled defaults (via [create_default_config_files][]).
- [TimerService][]: `setup timers` — generates systemd template units (`archcare@.service` /
    `archcare@.timer`), installs them into `/etc/systemd/system`, reloads the daemon, and
    optionally enables+starts one timer per automated task.

The module also provides [resolve_systemd_target_user][], which determines the non-root user that
timer units should execute as (via `SUDO_USER`), and the private `_generate_systemd_templates`
helper producing the unit file contents.

!!! warning "Root requirement"
    Everything in `TimerService` targets system-level systemd units, so `setup timers` must run
    under `sudo`; otherwise [NotRootError][] is raised.

All methods return response DTOs from [archcare.services.responses][] so the CLI layer never handles
raw business state.

See Also:
    - [archcare.services.exceptions][]: Service-layer error hierarchy used here
    - [archcare.cli.commands.setup][]: CLI commands delegating to these services
"""

import pwd
from os import getenv
from pathlib import Path

from archcare.config import AppSettings, TaskConfig, create_default_config_files
from archcare.core.executor import TaskExecutor
from archcare.services.exceptions import (
    NotRootError,
    SystemdReloadError,
    UserDetectionError,
)
from archcare.services.responses import (
    ConfigInitResponse,
    InstallTemplatesResponse,
    ReloadSystemdResponse,
    TimerEnableResponse,
    TimerSetupResponse,
)
from archcare.utils import is_root, run_systemctl


def resolve_systemd_target_user() -> tuple[str, str]:
    """
    Determine the (user, home_dir) that systemd units should run as.

    Must be called under `sudo`: reads `SUDO_USER` (set by sudo to the invoking user's name) and
    resolves their home directory via `pwd`.

    Returns:
        (tuple[str, str]): A tuple of:

            - `user` (`str`): The invoking (non-root) user's name.
            - `home_dir` (`str`): That user's home directory, used for the `WorkingDirectory`,
                `ExecStart`, and `ReadWritePaths` fields of the generated unit templates.

    Raises:
        NotRootError: If not running as root.
        UserDetectionError: If `SUDO_USER` is unset, or refers to a user that doesn't exist.

    Examples:
        ```bash
        # Correct usage (sudo sets SUDO_USER):
        sudo archcare setup timers
        # -> resolve_systemd_target_user() -> ("alice", "/home/alice")

        # Without sudo, NotRootError is raised before any detection:
        archcare setup timers
        # -> NotRootError: This command needs root privilege ...
        ```
    """
    if not is_root():
        raise NotRootError()

    # sudo sets SUDO_USER to the invoking user's name
    user = getenv("SUDO_USER")
    if not user:
        raise UserDetectionError("Could not determine the user. Make sure to run with sudo.")

    try:
        home_dir = pwd.getpwnam(user).pw_dir
    except KeyError:
        raise UserDetectionError(f"User '{user}' does not exist") from KeyError(user)

    return user, home_dir


class ConfigService:
    """
    Business logic for `setup config`.

    Wraps default configuration creation: detecting which TOML files already exist and
    bootstrapping `settings.toml`, `tasks.toml`, and `ignored-services.toml` from bundled defaults.

    Attributes:
        config_dir (Path): Directory configuration files live in (defaults to
            `AppSettings().config_dir`, i.e. `~/.config/archcare/`).
    """

    def __init__(self, config_dir: Path | None = None) -> None:
        """
        Initialize the config service.

        Args:
            config_dir (Path | None): Target configuration directory. Defaults to the standard
                `AppSettings().config_dir` when `None`.
        """
        self.config_dir = config_dir or AppSettings().config_dir

    def check_existing(self) -> list[Path]:
        """
        Return any existing `*.toml` config files, or an empty list.

        Returns:
            (list[Path]): Paths of existing TOML files in `config_dir` (not sorted; glob order).
                Empty if the directory doesn't exist or contains no TOML files.
        """
        if not self.config_dir.exists():
            return []
        return list(self.config_dir.glob("*.toml"))

    def initialize(self, force: bool = False) -> ConfigInitResponse:
        """
        Write default configuration files.

        Delegates to [create_default_config_files][], which creates missing files and — depending
        on `force` — either skips or overwrites existing ones.

        Args:
            force (bool): Whether to overwrite existing files. Defaults to `False` (existing files
                are left untouched and reported in the response's `skipped_files`).

        Returns:
            ConfigInitResponse: The config directory plus the `created_files`/`skipped_files` split.

        Side Effects:
            Creates `config_dir` (and parents) if missing, and writes TOML files into it.
        """
        created, skipped = create_default_config_files(self.config_dir, force=force)
        return ConfigInitResponse(
            config_dir=self.config_dir,
            created_files=created,
            skipped_files=skipped,
        )


class TimerService:
    """
    Business logic for `setup timers`.

    Installs the systemd template units (`archcare@.service`, `archcare@.timer`) into
    `/etc/systemd/system`, reloads the daemon, and optionally enables+starts one timer per automated
    task. The templates are generated from the target user's name and home directory so the service
    runs `archcare` as the right user.

    Attributes:
        SYSTEMD_DIR (Path): *(class-level)* Systemd unit directory units are installed to
            (`/etc/systemd/system`).
        user (str): The target (non-root) user timers run as, resolved via
            [resolve_systemd_target_user][].
        home_dir (str): The target user's home directory.
        service_file (Path): Full path of the installed `archcare@.service`.
        timer_file (Path): Full path of the installed `archcare@.timer`.
    """

    SYSTEMD_DIR = Path("/etc/systemd/system")

    def __init__(self, executor: TaskExecutor, user: str, home_dir: str) -> None:
        """
        Initialize the timer service.

        Args:
            executor (TaskExecutor): Shared executor providing the
                [ConfigLoader][archcare.config.loader.ConfigLoader] used to look up automated tasks.
            user (str): Target (non-root) user name for the units.
            home_dir (str): Target user's home directory, embedded into the generated unit templates
                (`WorkingDirectory`, `ExecStart`, `ReadWritePaths`).

        Side Effects:
            Pre-generates the service and timer unit contents (stored as
                `_service_content`/`_timer_content`) for later installation.
        """
        self._executor = executor
        self.user = user
        self.home_dir = home_dir
        self.service_file = self.SYSTEMD_DIR / "archcare@.service"
        self.timer_file = self.SYSTEMD_DIR / "archcare@.timer"
        self._service_content, self._timer_content = _generate_systemd_templates(home_dir, user)

    def get_automated_tasks(self) -> dict[str, TaskConfig]:
        """
        Load all automated tasks from configuration.

        Returns:
            (dict[str, TaskConfig]): Automated tasks keyed by task name, as
                read from `tasks.toml` via the executor's config loader.
        """
        tasks_config = self._executor.config_loader.load_tasks()
        return tasks_config.get_tasks_by_type("automated")

    def install_templates(self, dry_run: bool) -> InstallTemplatesResponse:
        """
        Install the systemd timer templates.

        Writes the pre-generated `archcare@.service` and `archcare@.timer` unit contents to
        `SYSTEMD_DIR` with `0644` permissions. In dry-run mode, no files are written and only
        the planned paths are reported.

        Args:
            dry_run (bool): When `True`, skip all filesystem writes and only
                report the target paths.

        Returns:
            InstallTemplatesResponse: The service/timer file paths and whether this was a dry run.

        Raises:
            OSError: If writing or chmodding the unit files fails (e.g., missing root privileges).

        Side Effects:
            Creates/overwrites the two systemd templates in /etc/systemd/system` (unless `dry_run`).
        """
        if not dry_run:
            self.service_file.write_text(self._service_content)
            self.service_file.chmod(0o644)
            self.timer_file.write_text(self._timer_content)
            self.timer_file.chmod(0o644)

        return InstallTemplatesResponse(
            service_file=self.service_file, timer_file=self.timer_file, dry_run=dry_run
        )

    @staticmethod
    def reload(dry_run: bool) -> ReloadSystemdResponse:
        """
        Reload the systemd daemon so new unit files are picked up.

        Args:
            dry_run (bool): When `True`, skip the actual `systemctl daemon-reload` and only report.

        Returns:
            ReloadSystemdResponse: Confirms whether the reload was performed or skipped as a
                dry run.

        Raises:
            SystemdReloadError: If `systemctl daemon-reload` fails.
        """
        if not dry_run:
            result = run_systemctl(["daemon-reload"])
            if not result.success:
                raise SystemdReloadError()
        return ReloadSystemdResponse(dry_run=dry_run)

    @staticmethod
    def setup_timers(
        automated_tasks: dict[str, TaskConfig], dry_run: bool, enable: bool
    ) -> TimerSetupResponse:
        """
        Optionally enable+start a timer for each automated task.

        Runs `systemctl enable --now archcare@<task>.timer` for every given automated task, then
        queries `systemctl list-timers archcare@*` to report the resulting timer state.
        `enabled_timers` and `timer_status` stay empty/`None` unless `enable=True` and
        `dry_run=False`. Note that individual enable failures are not fatal — they are recorded
        per-timer in the response's `enabled_timers` list.

        Args:
            automated_tasks (dict[str, TaskConfig]): Automated tasks to set up timers for, keyed by
                task name (from [get_automated_tasks][]).
            dry_run (bool): When `True`, skip all systemctl invocations.
            enable (bool): Whether to enable+start the timers; when `False`, the response is
                returned with empty results.

        Returns:
            TimerSetupResponse: The automated tasks, per-timer enable outcomes, and the raw
                `systemctl list-timers` output (when timers were enabled).

        Side Effects:
            Enables and starts `archcare@<task>.timer` units via systemctl
                (unless `dry_run` or `enable=False`).
        """
        enabled_timers: list[TimerEnableResponse] = []
        timer_status: str | None = None

        if enable and not dry_run:
            for task_name in automated_tasks:
                timer_name = f"archcare@{task_name}.timer"
                result = run_systemctl(["enable", "--now", timer_name])
                enabled_timers.append(
                    TimerEnableResponse(timer_name=timer_name, enabled=result.success)
                )

            status_result = run_systemctl(["list-timers", "archcare@*"])
            if status_result.success:
                timer_status = status_result.stdout

        return TimerSetupResponse(automated_tasks, enabled_timers, timer_status)


def _generate_systemd_templates(home_dir: str, user: str) -> tuple[str, str]:
    """
    Generate the systemd unit file contents for the target user.

    Builds the `archcare@.service` template (runs `archcare task run %i` as root with
    `ARCHCARE_USER` set to the target user, with working directory, logging, security hardening,
    resource limits, and writable-path restrictions derived from the home directory) and the
    `archcare@.timer` template (daily schedule, persistent, randomized delay).

    Args:
        home_dir (str): Target user's home directory; used for `WorkingDirectory`, `ExecStart`,
            and `ReadWritePaths`.
        user (str): Target user's name; exported to the unit as `ARCHCARE_USER` so tasks resolve
            the correct config/state paths.

    Returns:
        (tuple[str, str]): The full INI contents of the service unit and the timer unit, ready
            to be written to `archcare@.service`/`archcare@.timer`.

    See Also:
        - `TimerService`: Consumes these templates during `install_templates()`
    """
    # Service template content
    service_content = f"""[Unit]
Description=Archcare maintenance task: %i
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=root
Environment="ARCHCARE_USER={user}"

# Working directory
WorkingDirectory={home_dir}

# Run the task
ExecStart={home_dir}/.local/bin/archcare task run %i

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=archcare-%i

# Security hardening
PrivateTmp=yes
NoNewPrivileges=yes
ProtectSystem=strict

# Allow access to necessary paths
ReadWritePaths={home_dir}/.config/archcare {home_dir}/.local/state/archcare /etc/pacman.d

# Resource limits
CPUQuota=50%
MemoryMax=1G
TimeoutStartSec=30min

# Don't restart on failure
Restart=no

[Install]
WantedBy=multi-user.target
"""
    # Timer template content
    timer_content = """[Unit]
Description=Archcare maintenance timer: %i
Requires=archcare@%i.service

[Timer]
# Default schedule (override per-task with drop-ins)
OnCalendar=daily

# Run if missed while system was off
Persistent=yes

# Randomize start time to avoid load spikes
RandomizedDelaySec=1h

# Accuracy (can wake from suspend)
AccuracySec=12h

[Install]
WantedBy=timers.target
"""
    return service_content, timer_content
