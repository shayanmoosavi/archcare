"""
Provide console output utilities using the Rich library for Archcare's CLI.

This module encapsulates formatting and presentation helpers to ensure the CLI emits consistent,
clear, and visually appealing output. It configures a global `rich.console.Console` instance and
offers functions for:

- **Status reporting**: [print_success][], [print_error][], [print_warning][], and [print_info][]
    using standard iconography and color codes.
- **Layout structures**: [print_header][], [print_panel][], and [print_table][] for presenting dense
    or structured information (such as task tables or details).
- **Environment adaptive muting**: [configure_console][] automatically mutes outputs globally in
    non-interactive environments (e.g., systemd timers).

See Also:
    - [archcare.cli.app][]: The main CLI application where the `Console` instance gets configured.
    - [archcare.cli.presenters][]: The CLI presenters that use these utilities.
"""

from typing import Literal

from rich import box
from rich.console import Console, RenderableType
from rich.panel import Panel
from rich.table import Table

# Global console instance
console = Console()


def configure_console(is_interactive: bool = True) -> None:
    """
    Configure the global console instance for interactive or silent modes.

    In non-interactive environments (such as when Archcare is triggered by a systemd timer
    or run in a background daemon), this function mutes all standard output globally.
    This removes the need to manually check interactive status flags at every print statement.

    Args:
        is_interactive (bool): If True, enables beautiful terminal output. If False,
            sets the global console's quiet mode to True, suppressing all prints.
            Defaults to `True`.

    Examples:
        >>> from archcare.utils.output import configure_console, console
        >>> configure_console(is_interactive=False)
        >>> console.quiet
        True
        >>> configure_console(is_interactive=True)
        >>> console.quiet
        False
    """
    console.quiet = not is_interactive


# -----------------------------------------------------------------------------
# Status message helpers
# -----------------------------------------------------------------------------


def print_success(message: str) -> None:
    """
    Print a success message prefixed with a checkmark symbol in bold green.

    This should be used to report successfully completed operations or tasks that
    ran without any issues.

    Args:
        message (str): The success message text to display.

    Examples:
        >>> from archcare.utils.output import print_success
        >>> print_success("Database initialized successfully.")
        ✓ Database initialized successfully.
    """
    console.print(f"✓ {message}", style="bold green")


def print_error(message: str) -> None:
    """
    Print an error message prefixed with a cross symbol in bold red.

    This should be used to report critical failures, unhandled exceptions, or
    unsuccessful task completions.

    Args:
        message (str): The error message text to display.

    Examples:
        >>> from archcare.utils.output import print_error
        >>> print_error("Failed to connect to mirror servers.")
        ✗ Failed to connect to mirror servers.
    """
    console.print(f"✗ {message}", style="bold red")


def print_warning(message: str) -> None:
    """
    Print a warning message prefixed with a warning icon in bold yellow.

    This should be used to highlight non-critical issues, low disk space warnings,
    overdue scheduled runs, or other conditions requiring user attention.

    Args:
        message (str): The warning message text to display.

    Examples:
        >>> from archcare.utils.output import print_warning
        >>> print_warning("Disk utilization has exceeded 80%.")
        ⚠ Disk utilization has exceeded 80%.
    """
    console.print(f"⚠ {message}", style="bold yellow")


def print_info(message: str) -> None:
    """
    Print an informational message prefixed with an info icon in bold blue.

    This should be used to emit status updates, contextual descriptions, or generic
    operation milestones to the user.

    Args:
        message (str): The informational message text to display.

    Examples:
        >>> from archcare.utils.output import print_info
        >>> print_info("Checking systemd service states...")
        ℹ Checking systemd service states...
    """
    console.print(f"ℹ {message}", style="bold blue")


def print_header(title: str) -> None:
    """
    Print a bold cyan section header followed by a matching horizontal separator line.

    This is useful for separating distinct stages or command divisions within long-running
    CLI commands.

    Args:
        title (str): The header title text.

    Examples:
        >>> from archcare.utils.output import print_header
        >>> print_header("System Health Check")
        <BLANKLINE>
        System Health Check
        ───────────────────
    """
    console.print(f"\n[bold cyan]{title}[/bold cyan]")
    console.print("─" * len(title))


# -----------------------------------------------------------------------------
# Containers & Layouts
# -----------------------------------------------------------------------------


def print_panel(title: str, content: str | RenderableType, border_style: str = "cyan") -> None:
    """
    Print a bordered, rounded panel with a styled title.

    Creates and displays a Rich Panel containing string or other Renderable components. Panels are
    excellent for isolating log blocks, detailed summary metrics, or important notice banners.

    Args:
        title (str): The text title to overlay onto the top border of the panel.
        content (str | RenderableType): The text content or any Rich renderable (e.g. Table, Group)
            to embed within the panel.
        border_style (str): The styling or color string to apply to the panel border
            and title (e.g., "green", "yellow", "red", "cyan"). Defaults to "cyan".

    Examples:
        >>> from archcare.utils.output import print_panel
        >>> print_panel("System Logs", "Log content lines here", "cyan")
        ╭───── System Logs ──────╮
        │ Log content lines here │
        ╰────────────────────────╯
    """
    panel = Panel(
        content,
        title=f"[bold {border_style}]{title}[/bold {border_style}]",
        border_style=border_style,
        box=box.ROUNDED,
        expand=False,
    )
    console.print(panel)


def print_table(
    title: str,
    headers: list[str],
    rows: list[list[str | RenderableType]],
    justify: list[Literal["default", "left", "center", "right", "full"]] | None = None,
) -> None:
    """
    Print a standardized, rounded data table.

    Displays tabular data with automatic column formatting, optional alignments per column,
    and rounded borders. This is used to display task scheduled table or general diagnostics.

    Args:
        title (str): The title displayed above the table.
        headers (list[str]): The header labels for each column.
        rows (list[list[str | RenderableType]]): A list of rows, where each row contains
            a cell item (string or a Rich renderable) for every column.
        justify (list[Literal["default", "left", "center", "right", "full"]] | None): Optional list
            of alignments for each column. Each element must be one of "default", "left", "center",
            "right", or "full". If omitted or incomplete, columns default to "left" alignment.

    Examples:
        >>> from archcare.utils.output import print_table
        >>> print_table(  # doctest: +NORMALIZE_WHITESPACE
        ...     "Active Services",
        ...     ["Service", "Status"],
        ...     [["sshd.service", "active"]],
        ... )
                Active Services
            ╭──────────────┬────────╮
            │ Service      │ Status │
            ├──────────────┼────────┤
            │ sshd.service │ active │
            ╰──────────────┴────────╯
    """
    table = Table(
        title=title,
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
    )

    for i, header in enumerate(headers):
        col_justify = justify[i] if justify and i < len(justify) else "left"
        table.add_column(header, justify=col_justify)

    for row in rows:
        table.add_row(*row)

    console.print(table)
