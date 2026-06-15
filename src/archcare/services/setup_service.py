"""Setup service - business logic for `setup config` and `setup timers`."""

from os import getenv
import pwd
from pathlib import Path

from archcare.config import TaskConfig, create_default_config_files
from archcare.core import TaskExecutor
from archcare.services.exceptions import (
    NotRootError,
    UserDetectionError,
    SystemdReloadError,
)
from archcare.services.responses import (
    ConfigInitResponse,
    InstallTemplatesResponse,
    ReloadSystemdResponse,
    EnableTimersResponse,
)
from archcare.utils import is_root, run_systemctl


def resolve_systemd_target_user() -> tuple[str, str]:
    """
    Determine the (user, home_dir) that systemd units should run as.

    Raises:
        NotRootError: If not running as root.
        UserDetectionError: If SUDO_USER is unset, or refers to a user
            that doesn't exist.
    """
    if not is_root():
        raise NotRootError()

    # sudo sets SUDO_USER to the invoking user's name
    user = getenv("SUDO_USER")
    if not user:
        raise UserDetectionError(
            "Could not determine the user. Make sure to run with sudo."
        )

    try:
        home_dir = pwd.getpwnam(user).pw_dir
    except KeyError:
        raise UserDetectionError(f"User '{user}' does not exist")

    return user, home_dir


class ConfigService:
    """Business logic for `setup config`."""

    def __init__(self, config_dir: Path | None = None) -> None:
        self.config_dir = config_dir or (Path.home() / ".config/archcare")

    def check_existing(self) -> list[Path]:
        """Return any existing *.toml config files, or an empty list."""
        if not self.config_dir.exists():
            return []
        return list(self.config_dir.glob("*.toml"))

    def initialize(self) -> ConfigInitResponse:
        """Write default configuration files, overwriting any existing ones."""
        create_default_config_files(self.config_dir)
        return ConfigInitResponse(config_dir=self.config_dir)


class TimerService:
    """Business logic for `setup timers`."""

    SYSTEMD_DIR = Path("/etc/systemd/system")

    def __init__(self, executor: TaskExecutor, user: str, home_dir: str) -> None:
        self._executor = executor
        self.user = user
        self.home_dir = home_dir
        self.service_file = self.SYSTEMD_DIR / "archcare@.service"
        self.timer_file = self.SYSTEMD_DIR / "archcare@.timer"
        self._service_content, self._timer_content = _generate_systemd_templates(
            home_dir, user
        )

    def get_automated_tasks(self) -> dict[str, TaskConfig]:
        tasks_config = self._executor.config_loader.load_tasks()
        return tasks_config.get_tasks_by_type("automated")

    def install_templates(self, dry_run: bool) -> InstallTemplatesResponse:
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
        """Raises SystemdReloadError if `systemctl daemon-reload` fails."""
        try:
            _reload_systemd(dry_run)
        except SystemdReloadError:
            return ReloadSystemdResponse(success=False)
        return ReloadSystemdResponse(success=True)

    @staticmethod
    def setup_timers(
        automated_tasks: dict[str, TaskConfig], dry_run: bool, enable: bool
    ) -> EnableTimersResponse:
        """Enables the timers and retrieves the current timer status."""

        enabled = []
        failed = []
        status_output = None

        if enable and not dry_run:
            for task_name in automated_tasks.keys():
                timer_name = f"archcare@{task_name}.timer"
                result = run_systemctl(["enable", "--now", timer_name])
                if result.success:
                    enabled.append(timer_name)
                else:
                    failed.append(timer_name)

            status_result = run_systemctl(["list-timers", "archcare@*"])
            if status_result.success:
                status_output = status_result.stdout

        return EnableTimersResponse(
            enabled_timers=enabled,
            failed_timers=failed,
            timer_status_output=status_output,
        )


def _generate_systemd_templates(home_dir: str, user: str) -> tuple[str, str]:
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
    timer_content = f"""[Unit]
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


def _reload_systemd(dry_run: bool) -> None:
    if not dry_run:
        result = run_systemctl(["daemon-reload"])
        if not result.success:
            raise SystemdReloadError()
