"""Custom presenter for maintenance-check task"""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from archcare.core.models import MaintenanceCheckResult, MaintenanceIssue


class MaintenanceCheckPresenter:
    """Renders MaintenanceCheckResult to the terminal."""

    @staticmethod
    def render(
        result: MaintenanceCheckResult,
        is_interactive: bool = True,
        require_acknowledgment: bool = False,
    ) -> None:
        """
        Render the full maintenance check output.

        Args:
            result: The maintenance check result to render.
            is_interactive: Whether the command is running interactively.
                Non-interactive (systemd) runs skip the acknowledgment prompt.
            require_acknowledgment: Whether to block on user acknowledgment
                when critical issues are found (from settings).
        """
        console = Console()

        if not result.has_issues:
            msg = "✓ No maintenance issues found! Your system is healthy :)"
            console.print()
            console.print(
                Panel(
                    msg,
                    style="green",
                    border_style="green",
                    width=len(msg) + 4,
                )
            )
            return

        console.print()

        if result.critical_issues:
            MaintenanceCheckPresenter._render_issues_table(
                console,
                title="🟥 Critical Issues",
                issues=result.critical_issues,
                style="red",
            )

        if result.warning_issues:
            MaintenanceCheckPresenter._render_issues_table(
                console,
                title="🟨 Warning Issues",
                issues=result.warning_issues,
                style="yellow",
            )

        if result.info_issues:
            MaintenanceCheckPresenter._render_issues_table(
                console,
                title="🟦 Information",
                issues=result.info_issues,
                style="blue",
            )

        if result.critical_issues and require_acknowledgment and is_interactive:
            console.print()
            console.print(
                "[bold red]Critical issues require your attention![/bold red]"
            )
            console.input("Press Enter to acknowledge... ")

    @staticmethod
    def _render_issues_table(
        console: Console,
        title: str,
        issues: list[MaintenanceIssue],
        style: str,
    ) -> None:
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
