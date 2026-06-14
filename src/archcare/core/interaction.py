"""Interaction port for the Archcare core layer."""

from typing import Protocol


class TaskInteraction(Protocol):
    """Port through which TaskExecutor asks for user attention/input."""

    def notify(self, message: str, level: str = "info") -> None:
        """Surface an informational or warning message to the user."""
        ...

    @staticmethod
    def confirm(prompt: str) -> bool:
        """Ask a yes/no question; return True if the user confirms."""
        ...


class NonInteractive:
    """
    Default interaction used when none is supplied (tests, scripts,
    any caller that doesn't need user prompts).
    """

    def notify(self, message: str, level: str = "info") -> None:
        pass

    @staticmethod
    def confirm(prompt: str) -> bool:
        return False
