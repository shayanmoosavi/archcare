"""
Presenter for the `task` command group.

Owns all terminal rendering for TaskService results.
"""

from archcare.config import AppSettings, TaskStatus
from archcare.core import MaintenanceCheckDetails, TaskRegistry, TaskResult
from archcare.services.responses import (
    TaskListResponse,
    TaskRunResponse,
    TaskStatusResponse,
)
from archcare.utils.output import (
    console,
    print_error,
    print_header,
    print_info,
    print_panel,
    print_success,
    print_table,
    print_warning,
)

from .maintenance_presenter import MaintenanceCheckPresenter


class TaskPresenter:
    """Renders TaskService results and errors to the terminal."""

    def __init__(self, task_registry: TaskRegistry) -> None:
        self._task_registry = task_registry

    def render_run(
        self, response: TaskRunResponse, settings: AppSettings, verbose: bool = False
    ) -> None:
        if not response.outcome.is_skipped():
            print_header(f"Running Task: {response.task_name}")

        details = response.outcome.details

        # Maintenance issues table rendering
        if isinstance(details, MaintenanceCheckDetails):
            report_dir = settings.report_dir
            mc_settings = settings.maintenance_check

            # Do not render if output_mode = 'file'
            if mc_settings.output_mode != "file":
                MaintenanceCheckPresenter.render(
                    details,
                    is_interactive=response.is_interactive,
                    require_acknowledgment=mc_settings.require_acknowledgment,
                )
                if mc_settings.output_mode == "both":
                    print_info(f"You can also find the report in {report_dir}")
            else:
                print_info(
                    f"Output mode was set to 'file', check the report in {report_dir}"
                )
        console.print()

        # Render the task panel
        panel_content = self._format_task_details(
            response.task_name, response.outcome, verbose
        )
        print_panel(
            title=f"Task Result: {response.task_name}",
            content=panel_content,
            border_style="cyan",
        )

    def render_status(self, response: TaskStatusResponse) -> None:

        if response.due_only and not response.schedule_info:
            print_success("No tasks currently due!")
            return

        console.print()

        self._print_schedule_table(response)

        if response.summary:
            console.print()
            # Convert dict to panel content
            lines = [
                f"[bold]{key.replace('_', ' ').title()}:[/bold] {value}"
                for key, value in response.summary.items()
            ]
            print_panel("Summary", "\n".join(lines))

    @staticmethod
    def _print_schedule_table(response: TaskStatusResponse):
        # Build the data in the Presenter
        headers = ["Status", "Task", "Last Run", "Due"]
        rows = []

        for info in response.schedule_info:
            if info.days_overdue > 0:
                status, due_text = "[red]✗ DUE[/red]", f"[red]{info.reason}[/red]"
            elif info.is_due:
                status, due_text = (
                    "[yellow]⚠ DUE[/yellow]",
                    f"[yellow]{info.reason}[/yellow]",
                )
            else:
                status, due_text = (
                    "[green]✓ OK[/green]",
                    f"[green]{info.reason}[/green]",
                )

            last_run = (
                info.last_run.strftime("%Y-%m-%d") if info.last_run else "[dim]Never[/dim]"
            )
            rows.append([status, info.task_name, last_run, due_text])

        # Pass standard data to the generic UI primitive
        print_table(
            title="Task Schedule",
            headers=headers,
            rows=rows,  # ty:ignore[invalid-argument-type]
            justify=["center", "left", "right", "right"],
        )

    @staticmethod
    def render_list(response: TaskListResponse) -> None:
        print_header("Available Tasks")

        if not response.tasks:
            print_warning("No tasks found!")
            return

        for name, config in response.tasks.items():
            status_icon = "✓" if config.enabled else "✗"
            type_badge = f"[cyan]{config.task_type.value}[/cyan]"
            freq = f"every {config.frequency} days"

            console.print(f"{status_icon} [bold]{name}[/bold] {type_badge} ({freq})")
            console.print(f"  {config.description}")
            console.print()

    @staticmethod
    def not_found(task_name: str) -> None:
        print_error(f"Task not found: {task_name}")
        print_info("Use 'archcare task list' to see available tasks")

    @staticmethod
    def empty() -> None:
        print_error("Tasks file is empty or invalid.")
        print_info("See the logs for more details.")
        print_info(
            "If archcare isn't initialized, run 'archcare setup config' to "
            "create a new configuration or add tasks manually."
        )

    @staticmethod
    def invalid_task_type() -> None:
        print_error("Type must be 'automated' or 'manual'")

    @staticmethod
    def error(message: str) -> None:
        print_error(message)

    @staticmethod
    def aborted(task_name: str) -> None:
        console.print()
        print_warning(f"Task '{task_name}' execution aborted")

    @staticmethod
    def _get_status_text(status: TaskStatus) -> str:
        """Helper to map TaskStatus to stylized Rich text."""
        match status:
            case TaskStatus.SUCCESS:
                return "[green]✓ SUCCESS[/green]"
            case TaskStatus.FAILURE:
                return "[red]⨯ FAILURE[/red]"
            case TaskStatus.PARTIAL:
                return "[yellow]⚠ PARTIAL[/yellow]"
            case _:  # SKIPPED
                return "[blue]⤳ SKIPPED[/blue]"

    def _format_task_details(
        self, task_name: str, result: TaskResult, verbose: bool
    ) -> str:
        """Builds the string for the panel using the Formatter Factory."""

        # Build the universal outer shell
        lines = [
            f"[bold]Status:[/bold] {self._get_status_text(result.status)}",
            f"[bold]Message:[/bold] {result.message}",
            f"[bold]Duration:[/bold] {result.duration_seconds:.2f}s",
        ]

        if result.error:
            lines.append(f"[bold red]Error:[/bold red] {result.error}")

        # Delegate the domain details to the factory if verbose
        if verbose and result.details is not None:
            lines.append("\n[bold]Details:[/bold]")
            formatter_class = self._task_registry.get_formatter_class(task_name)
            lines.extend(formatter_class().format(result.details))

        return "\n".join(lines)
