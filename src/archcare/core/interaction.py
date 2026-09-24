"""
Interaction port for the Archcare core layer.

This module defines the user interaction interface ([`TaskInteraction`][]) and its
default non-interactive implementation ([`NonInteractive`][]). It establishes the boundary
(port) between core task execution logic and direct user communication, such as displaying
desktop notifications or asking for confirmation during potentially destructive actions.

By using this boundary, core task execution remains decoupled from the specific user interface
(e.g., CLI, desktop notifier, or daemon), allowing different presentation layers to adapt
how messages and confirmation questions are surfaced to the user.

Key Concepts:
    - **Port**: The [`TaskInteraction`][] protocol defines the interface for raising alerts
      and prompting for user input.
    - **Adapter**: Interactive presenters (like `CliInteraction` or desktop notification scripts)
      act as adapters implementing this port.
    - **Non-Interactive Mode**: For non-interactive environments (e.g., testing or automated runs
      via systemd), the system falls back to [`NonInteractive`][].

See Also:
    - [`CliInteraction`][archcare.cli.interaction.CliInteraction]: CLI-specific interactive
      implementation.
    - [`archcare.core.notifications`][]: Desktop notifications system using standard protocols.
"""

from typing import Protocol


class TaskInteraction(Protocol):
    """
    Port through which TaskExecutor asks for user attention/input.

    This protocol specifies the interface for raising alerts and getting user input
    concerning task execution choices (e.g., confirming a rollback or mirrorlist override).

    By implementing this protocol, any interface layer (interactive CLI shell, graphical prompt,
    or web daemon) can control how warnings are delivered and how users approve critical actions.

    Examples:
        >>> from archcare.core.interaction import TaskInteraction
        >>>
        >>> class PrintInteraction:
        ...     def notify(self, message: str, level: str = "info") -> None:
        ...         print(f"[{level.upper()}] {message}")
        ...
        ...     @staticmethod
        ...     def confirm(prompt: str) -> bool:
        ...         print(f"Prompting: {prompt}")
        ...         return True
        >>>
        >>> # Ensure compliance with the TaskInteraction protocol
        >>> interaction: TaskInteraction = PrintInteraction()
        >>> interaction.notify("Mirror list outdated", level="warning")
        [WARNING] Mirror list outdated
        >>> interaction.confirm("Do you want to update?")
        Prompting: Do you want to update?
        True

    See Also:
        [`NonInteractive`][]: The default non-interactive implementation of this protocol.
    """

    def notify(self, message: str, level: str = "info") -> None:
        """
        Surface an informational or warning message to the user.

        Used to broadcast execution milestones, runtime issues, or critical notifications
        to the user's desktop, system log, or console depending on the active adapter.

        Args:
            message (str): The human-readable message content to display.
            level (str): The urgency level of the message. Typically `'info'`,
                `'warning'`, `'error'`, or `'success'`. Defaults to `'info'`.
        """
        ...

    @staticmethod
    def confirm(prompt: str) -> bool:
        """
        Ask a yes/no question; return True if the user confirms.

        Prompts the user for a yes/no response when a critical or irreversible action
        is about to take place (e.g., writing a new mirrorlist over the system default).

        Args:
            prompt (str): The message prompt or question to display to the user.

        Returns:
            bool: `True` if the user approved the action, `False` otherwise.
        """
        ...


class NonInteractive:
    """
    Default interaction used when none is supplied.

    This class serves as a "null object" or "no-op" implementation of the
    [`TaskInteraction`][archcare.core.interaction.TaskInteraction] protocol. It silently ignores
    all notifications and automatically declines all user prompts. This is suitable for:

    - Running tasks automatically via background daemons or cron jobs (e.g., systemd timers)
    - Non-interactive script environments
    - Automated unit tests where mocking interaction inputs is unnecessary

    Examples:
        >>> from archcare.core.interaction import NonInteractive
        >>> interaction = NonInteractive()
        >>> interaction.notify("Mirror update complete", level="success")
        >>> interaction.confirm("Do you want to apply updates?")
        False

    See Also:
        [`TaskInteraction`][]: Protocol describing the full interaction interface.
    """

    def notify(self, message: str, level: str = "info") -> None:
        """
        Surface an informational or warning message (no-op).

        Args:
            message (str): The human-readable message content.
            level (str): The urgency level of the message. Defaults to `'info'`.
        """

    @staticmethod
    def confirm(prompt: str) -> bool:
        """
        Ask a yes/no question; always returns False.

        Args:
            prompt (str): The message prompt or question.

        Returns:
            bool: Always `False`.
        """
        return False
