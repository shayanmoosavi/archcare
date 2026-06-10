"""
Console output utilities using Rich.

Provides consistent, beautiful output formatting for CLI.
"""

from typing import Any

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import box

from archcare.core.models import TaskResult, TaskStatus, MaintenanceIssue
from archcare.core.scheduler import TaskScheduleInfo

# Global console instance
console = Console()


def print_success(message: str) -> None:
    """Print success message in green."""
    console.print(f"✓ {message}", style="bold green")


def print_error(message: str) -> None:
    """Print error message in red."""
    console.print(f"✗ {message}", style="bold red")


def print_warning(message: str) -> None:
    """Print warning message in yellow."""
    console.print(f"⚠ {message}", style="bold yellow")


def print_info(message: str) -> None:
    """Print info message in blue."""
    console.print(f"ℹ {message}", style="bold blue")


def print_header(title: str) -> None:
    """
    Print a section header.

    Args:
        title: Header title
    """
    console.print(f"\n[bold cyan]{title}[/bold cyan]")
    console.print("─" * len(title))


def print_task_result(result: TaskResult, task_name: str) -> None:
    """
    Print task execution result with appropriate styling.

    Args:
        result: TaskResult from execution
        task_name: Name of the task

    Reason:
    - Consistent formatting across all task outputs
    - Color-coded status for quick scanning
    - Shows key information at a glance
    """
    # Status icon and color
    icon = ""
    color = ""
    match result.status:
        case TaskStatus.SUCCESS:
            icon = "✓"
            color = "green"
        case TaskStatus.FAILURE:
            icon = "✗"
            color = "red"
        case TaskStatus.PARTIAL:
            icon = "⚠"
            color = "yellow"
        case _:  # SKIPPED
            icon = "○"
            color = "blue"

    # Print status line
    console.print(
        f"[bold {color}]{icon} {task_name}[/bold {color}] "
        f"({result.duration_seconds:.2f}s)"
    )

    # Print message
    console.print(f"  {result.message}")

    # Print error if present
    if result.error:
        console.print(f"  [red]Error: {result.error}[/red]")


def print_schedule_table(schedule_info: list[TaskScheduleInfo]) -> None:
    """
    Print a table of task schedules.

    Args:
        schedule_info: List of TaskScheduleInfo to display
    """
    if not schedule_info:
        print_info("No tasks configured")
        return

    table = Table(
        title="Task Schedule",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
    )

    table.add_column("Status", justify="center", width=6)
    table.add_column("Task", style="bold")
    table.add_column("Last Run", justify="right")
    table.add_column("Due", justify="right")

    for info in schedule_info:

        # Status indicator
        status = _colorize_cell(info, is_status_col=True)

        # Format dates
        last_run = (
            info.last_run.strftime("%Y-%m-%d") if info.last_run else "[dim]Never[/dim]"
        )

        # Due task info
        due_text = _colorize_cell(info, is_status_col=False)

        table.add_row(status, info.task_name, last_run, due_text)

    console.print(table)


def _colorize_cell(info: TaskScheduleInfo, is_status_col: bool) -> str:
    """Colorize a table cell based on due status."""
    if is_status_col:
        if info.days_overdue > 0:
            colorized_cell = "[red]✗ DUE[/red]"
        elif info.is_due:
            colorized_cell = "[yellow]⚠ DUE[/yellow]"
        else:
            colorized_cell = "[green]✓ OK[/green]"
    else:
        if info.days_overdue > 0:
            colorized_cell = f"[red]{info.reason}[/red]"
        elif info.is_due:
            colorized_cell = f"[yellow]{info.reason}[/yellow]"
        else:
            colorized_cell = f"[green]{info.reason}[/green]"

    return colorized_cell


def _format_other_details(lines: list[str], details: dict[str, Any]):
    """Format generic task details for display."""
    for key, value in details.items():
        if not key.startswith("_"):  # Skip internal keys
            lines.append(f"  {key}: {value}")


def print_task_details(
    task_name: str, result: TaskResult, show_details: bool = True
) -> None:
    """
    Print detailed task result information.

    Args:
        task_name: Name of the task
        result: TaskResult with details
        show_details: Whether to show the details dict
    """
    # Map status to Rich styled text
    status_mapping = {
        "success": "[green]✓ SUCCESS[/green]",
        "failure": "[red]⨯ FAILURE[/red]",
        "skipped": "[blue]⤳ SKIPPED[/blue]",
        "partial": "[yellow]⚠ PARTIAL[/yellow]",
    }

    # Create panel content
    lines = [
        f"[bold]Status:[/bold] {status_mapping[str(result.status)]}",
        f"[bold]Message:[/bold] {result.message}",
        f"[bold]Duration:[/bold] {result.duration_seconds:.2f}s",
    ]

    if result.error:
        lines.append(f"[bold red]Error:[/bold red] {result.error}")

    # Add details if requested and present
    if show_details and result.details:
        lines.append("\n[bold]Details:[/bold]")

        # Format details based on task type
        formatters = {
            "failed-services": _format_failed_services_details,
            "health-check": _format_health_check_details,
            "maintenance-check": _format_maintenance_check_details,
        }
        formatter = formatters.get(task_name, _format_other_details)
        formatter(lines, result.details)

    # Print in a panel
    panel = Panel(
        "\n".join(lines),
        title=f"[bold cyan]{task_name}[/bold cyan]",
        border_style="cyan",
        width=200,
    )
    console.print(panel)


# Failed services task related helpers
# ---------------------------------------------------------------------------------------------------


def _format_failed_services_details(lines: list[str], details: dict[str, Any]) -> None:
    """
    Format failed services details for display.

    Args:
        lines: List to append formatted lines to
        details: Task details dict
    """
    failed_services = details.get("failed_services", [])
    total = details.get("total_failed", 0)
    actual = details.get("actual_failures", 0)
    ignored = details.get("ignored", 0)

    lines.append(f"[blue]  Total failed: {total}[/blue]")
    lines.append(f"[red]  ⚠ Requiring attention: {actual}[/red]")
    lines.append(f"[dim]  Ignored: {ignored}[/dim]")

    if failed_services:
        lines.append("\n[bold]Failed Services:[/bold]")

        _add_failure_details(failed_services, lines)


def _add_failure_details(failed_services: list[dict[str, Any]], lines: list[str]):
    """Add detailed failed services information to lines."""
    for failure in failed_services:
        service = failure.get("service", "unknown")
        desc = failure.get("description", "")
        active = failure.get("active", "unknown")

        lines.append(f"  • [red]{service}[/red]")
        if desc:
            lines.append(f"    {desc}")
        lines.append(f"    Status: {active}")

        # Show a few log lines
        logs = failure.get("logs", [])
        if logs:
            lines.append("    Recent logs:")
            for log in logs[-3:]:  # Last 3 lines
                lines.append(f"      {log[:160]}")  # Truncate long lines


# ---------------------------------------------------------------------------------------------------

# Failed services task related helpers
# ---------------------------------------------------------------------------------------------------


def _format_health_check_details(lines: list[str], details: dict[str, Any]) -> None:
    """
    Format health check details for display.

    Args:
        lines: List to append formatted lines to
        details: Task details dict
    """
    issues = details.get("issues", [])
    warnings = details.get("warnings", [])
    summary = details.get("summary", {})

    # Show issues and warnings first
    if issues:
        lines.append("\n[bold red]Critical Issues:[/bold red]")
        for issue in issues:
            lines.append(f"  • {issue}")

    if warnings:
        lines.append("\n[bold yellow]Warnings:[/bold yellow]")
        for warning in warnings:
            lines.append(f"  • {warning}")

    # Show summary statistics
    _format_health_check_summary(lines, summary)


def _format_health_check_summary(lines: list[str], summary: dict[str, Any]):
    lines.append("\n[bold]System Summary:[/bold]")

    # Disk
    disk_pct = summary.get("disk_usage_percent", 0)
    disk_color = "red" if disk_pct > 90 else "yellow" if disk_pct > 80 else "green"
    lines.append(f"  Disk Usage: [{disk_color}]{disk_pct:.1f}%[/{disk_color}]")

    # Memory
    mem_pct = summary.get("memory_usage_percent", 0)
    mem_color = "red" if mem_pct > 90 else "yellow" if mem_pct > 80 else "green"
    lines.append(f"  Memory Usage: [{mem_color}]{mem_pct:.1f}%[/{mem_color}]")

    # CPU
    cpu_pct = summary.get("cpu_usage_percent", 0)
    cpu_color = "yellow" if cpu_pct > 90 else "green"
    lines.append(f"  CPU Usage: [{cpu_color}]{cpu_pct:.1f}%[/{cpu_color}]")

    # Filesystem errors
    fs_errors = summary.get("filesystem_errors_count", 0)
    if fs_errors > 0:
        lines.append(f"  Filesystem Errors: [red]{fs_errors}[/red]")

    # Pacman
    pacman_ok = summary.get("pacman_healthy", False)
    pacman_status = (
        "[green]Healthy[/green]" if pacman_ok else "[red]Issues Detected[/red]"
    )
    lines.append(f"  Pacman Database: {pacman_status}")

    packages_ok = summary.get("packages_healthy", False)
    packages_status = (
        "[green]Healthy[/green]" if packages_ok else "[red]Issues Detected[/red]"
    )
    lines.append(f"  Installed Package Files: {packages_status}")

    # Uptime
    uptime = summary.get("uptime", "unknown")
    lines.append(f"  System Uptime: {uptime}")


# ---------------------------------------------------------------------------------------------------


def _format_maintenance_check_details(lines: list[str], details: dict[str, Any]):
    """
    Format maintenance check details for display

    Args:
        lines: List to append formatted lines to
        details: Task details dict
    """
    lines.append("\n[bold]Summary: [/bold]")

    # Summary statistics
    total_tasks_monitored = details.get("total_tasks_monitored", -1)
    critical_count = details.get("critical_count", -1)
    warning_count = details.get("warning_count", -1)
    info_count = details.get("info_count", -1)

    lines.append(f"  Total tasks monitored: {total_tasks_monitored}")
    lines.append(f"  Critical issues: {critical_count}")
    lines.append(f"  Warning issues: {warning_count}")
    lines.append(f"  Informational issues: {info_count}")
    lines.append("")

    severity_mapping = {
        "critical": "[red]❗ CRITICAL[/red]",
        "warning": "[yellow]⚠ WARNING[/yellow]",
        "info": "[blue]ℹ INFO[/blue]",
    }

    tasks_needing_attention: list[MaintenanceIssue] = details["tasks_needing_attention"]
    if tasks_needing_attention:
        lines.append("[bold]Tasks needing attention: [/bold]")
        for maintenance_issue in tasks_needing_attention:
            lines.append(f"[blue]  • {maintenance_issue.task_name}[/blue]")
            lines.append(f"    ‒ {severity_mapping[str(maintenance_issue.severity)]}")


def print_summary_panel(title: str, stats: dict[str, Any]) -> None:
    """
    Print a summary panel with statistics.

    Args:
        title: Panel title
        stats: Dictionary of statistics to display
    """
    lines = []
    for key, value in stats.items():
        # Format key nicely (convert snake_case to Title Case)
        formatted_key = key.replace("_", " ").title()
        lines.append(f"[bold]{formatted_key}:[/bold] {value}")

    panel = Panel(
        "\n".join(lines), title=f"[bold cyan]{title}[/bold cyan]", border_style="cyan"
    )
    console.print(panel)


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


def confirm(message: str, default: bool = False) -> bool:
    """
    Ask user for confirmation.

    Args:
        message: Confirmation message
        default: Default value if user just presses Enter

    Returns:
        True if user confirmed, False otherwise
    """
    default_str = "Y/n" if default else "y/N"
    response = console.input(f"{message} [{default_str}] ").strip().lower()

    if not response:
        return default

    return response in ("y", "yes")


def print_divider() -> None:
    """Print a visual divider."""
    console.print("─" * console.width)
