"""
Setup service - business logic for `setup config` and `setup timers`.

No Typer, no print statements except where delegated to
`archcare.services.systemd`, which already owns systemd-specific progress
output (a pre-existing pattern, not introduced here).
"""

from os import getenv
import pwd
from pathlib import Path

from archcare.config import TaskConfig, create_default_config_files
from archcare.core import TaskExecutor
from archcare.services.exceptions import NotRootError, UserDetectionError
from archcare.services.responses import ConfigInitResponse
from archcare.services.systemd import (
    generate_systemd_templates,
    install_systemd_templates,
    reload_systemd,
    setup_systemd_timer,
)
from archcare.utils import is_root


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
    """
    Business logic for `setup timers`.

    Wraps `archcare.services.systemd` (template generation, installation,
    daemon reload, timer enabling) behind a single object scoped to one
    target user/home directory.
    """

    SYSTEMD_DIR = Path("/etc/systemd/system")

    def __init__(self, executor: TaskExecutor, user: str, home_dir: str) -> None:
        self._executor = executor
        self.user = user
        self.home_dir = home_dir
        self.service_file = self.SYSTEMD_DIR / "archcare@.service"
        self.timer_file = self.SYSTEMD_DIR / "archcare@.timer"
        self._service_content, self._timer_content = generate_systemd_templates(
            home_dir, user
        )

    def get_automated_tasks(self) -> dict[str, TaskConfig]:
        tasks_config = self._executor.config_loader.load_tasks()
        return tasks_config.get_tasks_by_type("automated")

    def install_templates(self, dry_run: bool) -> None:
        install_systemd_templates(
            dry_run,
            self._service_content,
            self.service_file,
            self._timer_content,
            self.timer_file,
        )

    @staticmethod
    def reload(dry_run: bool) -> None:
        """Raises SystemdReloadError if `systemctl daemon-reload` fails."""
        reload_systemd(dry_run)

    @staticmethod
    def setup_timers(
        automated_tasks: dict[str, TaskConfig], dry_run: bool, enable: bool
    ) -> None:
        setup_systemd_timer(automated_tasks, dry_run, enable)
