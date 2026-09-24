"""
Custom presenter for the maintenance-check task.

Provides [`MaintenanceCheckPresenter`][], which renders the severity-grouped issue report
produced by [`MaintenanceCheckTask`][archcare.tasks.maintenance_check.MaintenanceCheckTask]:
a "healthy" panel when no issues exist, otherwise one color-coded table per severity level (critical
/ warning / info), plus an optional interactive acknowledgment prompt for critical issues.

This presenter is invoked from
[`TaskPresenter.render_run`][archcare.cli.presenters.task_presenter.TaskPresenter.render_run]
whenever a maintenance-check run produces [`MaintenanceCheckDetails`][].
"""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from archcare.core import MaintenanceCheckDetails, MaintenanceIssue
from archcare.utils import console


class MaintenanceCheckPresenter:
    """
    Renders per-severity issue tables to the terminal.

    Consumes [`MaintenanceCheckDetails`][] and renders, in order: critical (red), warning (yellow),
    and info (blue) issue tables — each listing the affected task, the issue description, and a
    recommendation. A green "healthy" panel is shown when no issues were found. Optionally blocks
    for user acknowledgment when critical issues exist (interactive runs only).
    """

    @staticmethod
    def render(
        details: MaintenanceCheckDetails,
        is_interactive: bool = True,
        require_acknowledgment: bool = False,
    ) -> None:
        """
        Render the full maintenance check output.

        Renders the "healthy" panel when no issues exist; otherwise renders the
        critical/warning/info issue tables in that order, and — if critical issues are present,
        `require_acknowledgment` is set, and the run is interactive — pauses and waits for the user
        to press Enter before continuing.

        Args:
            details (MaintenanceCheckDetails): Maintenance check details to render (issue groups
                and summary).
            is_interactive (bool): Whether the command is running interactively. Non-interactive
                (systemd) runs skip the acknowledgment prompt. Defaults to `True`.
            require_acknowledgment (bool): Whether to block on user acknowledgment when critical
                issues are found (from the `maintenance_check` settings). Defaults to `False`.

        Side Effects:
            Prints the report to the terminal; may block waiting for user input when critical issues
                require acknowledgment.
        """

        if not details.summary.has_issues:
            msg = "✔ No maintenance issues found! Your system is healthy :)"
            console.print()
            console.print(
                Panel(
                    msg,
                    style="green",
                    border_style="green",
                    padding=(0, 2),
                    expand=False,
                )
            )
            return

        console.print()

        if details.critical_issues:
            MaintenanceCheckPresenter._render_issues_table(
                console,
                title="🟥 Critical Issues",
                issues=details.critical_issues,
                style="red",
            )

        if details.warning_issues:
            MaintenanceCheckPresenter._render_issues_table(
                console,
                title="🟨 Warning Issues",
                issues=details.warning_issues,
                style="yellow",
            )

        if details.info_issues:
            MaintenanceCheckPresenter._render_issues_table(
                console,
                title="🟦 Information",
                issues=details.info_issues,
                style="blue",
            )

        if details.critical_issues and require_acknowledgment and is_interactive:
            console.print()
            console.print("[bold red]Critical issues require your attention![/bold red]")
            console.input("Press Enter to acknowledge... ")

    @staticmethod
    def _render_issues_table(
        console: Console,
        title: str,
        issues: list[MaintenanceIssue],
        style: str,
    ) -> None:
        """
        Print one severity group as a Rich table.

        The table has three columns — Task (cyan), Issue (white), and Recommendation (green) —
        bordered in the given style, followed by a blank line for spacing.

        Args:
            console (Console): Rich console to print to.
            title (str): Table title (e.g., `"🟥 Critical Issues"`).
            issues (list[MaintenanceIssue]): Issues in this severity group, rendered in list order.
            style (str): Rich color style for the table border (e.g., `"red"`).
        """
        table = Table(title=title, show_header=True, border_style=style)
        table.add_column("Task", style="cyan", no_wrap=True)
        table.add_column("Issue", style="white")
        table.add_column("Recommendation", style="green")

        for issue in issues:
            table.add_row(
                issue.task_name,
                issue.description,
                issue.recommendation,
            )

        console.print(table)
        console.print()
