"""
CLI adapter for TaskExecutor's interaction port.

Wires TaskExecutor's notify()/confirm() calls to the existing Rich-based output helpers
and Typer's confirmation prompt.
"""

import typer

from archcare.utils import print_info, print_warning


class CliInteraction:
    """Terminal implementation of `archcare.core.interaction.TaskInteraction`."""

    def notify(self, message: str, level: str = "info") -> None:
        if level == "warning":
            print_warning(message)
        else:
            print_info(message)

    @staticmethod
    def confirm(prompt: str) -> bool:
        return typer.confirm(prompt)
