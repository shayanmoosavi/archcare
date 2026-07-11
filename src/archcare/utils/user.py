"""User context for Archcare.

Single source of truth for ARCHCARE_USER resolution.
"""

from dataclasses import dataclass
from os import getenv
from pathlib import Path

from .system import change_ownership_to_user, is_root


@dataclass(frozen=True)
class UserContext:
    """
    Resolves ARCHCARE_USER once per invocation.

    ARCHCARE_USER is set by the systemd service unit for scheduled runs;
    its absence means the command is running interactively.
    """

    archcare_user: str | None

    @property
    def is_interactive(self) -> bool:
        return self.archcare_user is None

    @classmethod
    def from_env(cls) -> "UserContext":
        return cls(archcare_user=getenv("ARCHCARE_USER"))

    def chown_if_root(self, *paths: Path) -> None:
        """
        Change ownership of the given paths to archcare_user, but only
        when running as root via systemd - interactive runs never chown,
        since there's no ARCHCARE_USER to hand ownership to.
        """
        if is_root() and self.archcare_user:
            for path in paths:
                change_ownership_to_user(path, self.archcare_user)
