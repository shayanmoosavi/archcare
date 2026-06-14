"""
CLI adapter for TaskExecutor's interaction port.

Wires TaskExecutor's notify()/confirm() calls to the existing Rich-based output helpers
and Typer's confirmation prompt.
"""

import typer

from archcare.utils.output import print_info, print_warning


class CliInteraction:
    """Terminal implementation of `archcare.core.interaction.TaskInteraction`."""

    def __init__(self, is_interactive: bool = True) -> None:
        self.is_interactive = is_interactive

    def notify(self, message: str, level: str = "info") -> None:
        if level == "warning":
            print_warning(message, self.is_interactive)
        else:
            print_info(message, self.is_interactive)

    @staticmethod
    def confirm(prompt: str) -> bool:
        return typer.confirm(prompt)
