"""
CLI adapter for TaskExecutor's interaction port.

Wires [TaskInteraction][archcare.core.interaction.TaskInteraction]'s
`notify()` and `confirm()` calls to the existing Rich-based output helpers
and Typer's confirmation prompt, letting core task code interact with the
user without depending on the CLI layer.

See Also:
    - [archcare.core.interaction][]: The port this adapter implements
    - [archcare.core.interaction.NonInteractive][]: The non-interactive
        counterpart used for systemd timer runs
"""

import typer

from archcare.utils import print_info, print_warning


class CliInteraction:
    """
    Terminal implementation of [TaskInteraction][archcare.core.interaction.TaskInteraction].

    Notifies via Rich-styled info/warning helpers and confirms via Typer's interactive yes/no
    prompt. Not usable when stdin isn't a TTY (e.g., systemd timer runs) — those use
    [NonInteractive][archcare.core.interaction.NonInteractive] implementation instead.
    """

    def notify(self, message: str, level: str = "info") -> None:
        """
        Surface an informational or warning message to the user.

        Args:
            message (str): Text to display.
            level (str): Message level — `"warning"` renders via the warning helper; anything else
                renders as info. Defaults to `"info"`.
        """
        if level == "warning":
            print_warning(message)
        else:
            print_info(message)

    @staticmethod
    def confirm(prompt: str) -> bool:
        """
        Prompt the user for confirmation.

        Blocks on an interactive Typer yes/no prompt until user responds.

        Args:
            prompt (str): Question shown to the user.

        Returns:
            bool: `True` if the user confirmed, `False` otherwise.
        """
        return typer.confirm(prompt)
