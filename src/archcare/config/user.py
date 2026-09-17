"""
Resolve and manage the Archcare execution user context.

Provides the single source of truth for determining whether the application is running interactively
or under a systemd timer, and handles conditional file ownership changes when running as root.

Key responsibilities:
    - Read `ARCHCARE_USER` environment variable (set by systemd service units)
    - Determine interactive vs. scheduled execution mode
    - Change file ownership to the target user when running as root

See Also:
    - [`is_root`][archcare.utils.is_root]: Root privilege detection utility
    - [`change_ownership_to_user`][archcare.utils.change_ownership_to_user]: Ownership modification
        utility
    - [`ConfigLoader`][]: Consumes `UserContext` for state file ownership
"""

from dataclasses import dataclass
from os import getenv
from pathlib import Path

from archcare.utils import change_ownership_to_user, is_root


@dataclass(frozen=True)
class UserContext:
    """
    Immutable context capturing the Archcare execution user.

    Resolves the `ARCHCARE_USER` environment variable once per invocation. This variable is set by
    the systemd service unit for scheduled runs; its absence indicates the command is running
    interactively.

    Attributes:
        archcare_user (str | None): The target username from the `ARCHCARE_USER` environment
            variable, or `None` if unset (interactive run).

    Examples:
        >>> import os
        >>> os.environ["ARCHCARE_USER"] = "alice"
        >>> ctx = UserContext.from_env()
        >>> ctx.archcare_user
        'alice'
        >>> ctx.is_interactive
        False
        >>> del os.environ["ARCHCARE_USER"]
        >>> UserContext.from_env().is_interactive
        True

    See Also:
        - [`is_root`][archcare.utils.is_root]: Root privilege detection
        - [`ConfigLoader`][]: Uses this for state file chown
    """

    archcare_user: str | None

    @property
    def is_interactive(self) -> bool:
        """
        Check if running in interactive mode (no `ARCHCARE_USER` set).

        Returns:
            bool: True if `ARCHCARE_USER` is not set (interactive CLI),
                False if running under systemd timer.
        """
        return self.archcare_user is None

    @classmethod
    def from_env(cls) -> "UserContext":
        """
        Create a `UserContext` by reading the `ARCHCARE_USER` environment variable.

        Returns:
            UserContext: New instance with `archcare_user` populated from
                the environment (or `None` if unset).

        Examples:
            >>> import os
            >>> os.environ["ARCHCARE_USER"] = "testuser"
            >>> ctx = UserContext.from_env()
            >>> ctx.archcare_user
            'testuser'
            >>> del os.environ["ARCHCARE_USER"]
            >>> UserContext.from_env().archcare_user is None
            True
        """
        return cls(archcare_user=getenv("ARCHCARE_USER"))

    def chown_if_root(self, *paths: Path) -> None:
        """
        Change ownership of paths to `archcare_user` if running as root.

        Only performs ownership changes when both conditions are met:

        1. The current process has root privileges (UID 0)
        2. An `archcare_user` was resolved from the environment

        Interactive runs never change ownership since there is no target
        user to hand ownership to.

        Args:
            *paths (pathlib.Path): One or more filesystem paths to change
                ownership of. Each path is processed independently.

        Raises:
            OSError: Propagated from `change_ownership_to_user` if the
                ownership change fails.

        Side Effects:
            Modifies filesystem ownership on the provided paths.

        See Also:
            - [`is_root`][archcare.utils.is_root]: Root privilege detection
            - [`change_ownership_to_user`][archcare.utils.change_ownership_to_user]:
                Actual ownership change
            - [`ConfigLoader.save_state`][]: Consumer of this method
        """
        if is_root() and self.archcare_user:
            for path in paths:
                change_ownership_to_user(path, self.archcare_user)
