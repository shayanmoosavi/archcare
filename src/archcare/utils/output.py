"""
Console output utilities using Rich.

Provides consistent, beautiful output formatting for CLI.
"""

from typing import Literal

from rich import box
from rich.console import Console, RenderableType
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

# Global console instance
console = Console()


def configure_console(is_interactive: bool = True) -> None:
    """
    Configure the global console instance.

    If non-interactive (e.g., running via systemd), this natively mutes
    all rich output globally, removing the need for manual checks.
    """
    console.quiet = not is_interactive


# -----------------------------------------------------------------------------
# Status message helpers
# -----------------------------------------------------------------------------


def print_success(message: str) -> None:
    """Print success message in green.

    Args:
        message: Message to print
    """
    console.print(f"✓ {message}", style="bold green")


def print_error(message: str) -> None:
    """Print error message in red.

    Args:
        message: Message to print
    """
    console.print(f"✗ {message}", style="bold red")


def print_warning(message: str) -> None:
    """Print warning message in yellow.

    Args:
        message: Message to print
    """
    console.print(f"⚠ {message}", style="bold yellow")


def print_info(message: str) -> None:
    """Print info message in blue.

    Args:
        message: Message to print
    """
    console.print(f"ℹ {message}", style="bold blue")


def print_header(title: str) -> None:
    """
    Print a section header.

    Args:
        title: Header title
    """
    console.print(f"\n[bold cyan]{title}[/bold cyan]")
    console.print("─" * len(title))


# -----------------------------------------------------------------------------
# Containers & Layouts
# -----------------------------------------------------------------------------


def print_panel(
    title: str, content: str | RenderableType, border_style: str = "cyan"
) -> None:
    """
    Print a bordered panel.

    Args:
        title: Panel title.
        content: String or Rich renderable to place inside the panel.
        border_style: Color/style of the border (default: cyan).
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
    Print a standardized data table.

    Args:
        title: Table title.
        headers: List of column header names.
        rows: List of rows, where each row is a list of cell contents.
        justify: Optional list of alignment strings per column.
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


# -----------------------------------------------------------------------------
# Progress indicators
# -----------------------------------------------------------------------------


def create_progress() -> Progress:
    """
    Create a progress indicator for long-running operations.

    Returns:
        Rich Progress object

    Example:
        with create_progress() as progress:
            task = progress.add_task("Running tasks...", total=None)
            # do work
            progress.update(task, completed=True)
    """
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    )
