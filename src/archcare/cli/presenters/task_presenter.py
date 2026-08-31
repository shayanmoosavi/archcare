"""
Presenter for the `task` command group.

Owns all terminal rendering for `TaskService` results. Translates the response DTOs from
[archcare.services.responses][] into Rich-based terminal output: result panels, schedule tables,
task listings, and error/warning messages. Task-specific detail rendering is delegated to the
per-task formatter classes registered in the [TaskRegistry][], and the maintenance-check report is
delegated to [MaintenanceCheckPresenter][].

See Also:
    - [TaskService][archcare.services.task_service.TaskService]: Producer of the responses
        rendered here
    - [MaintenanceCheckPresenter][]: Renderer for the maintenance-check report
"""

from rich.console import RenderableType

from archcare.config import AppSettings, TaskStatus
from archcare.core import MaintenanceCheckDetails, TaskRegistry, TaskResult
from archcare.services.responses import (
    TaskListResponse,
    TaskRunResponse,
    TaskStatusResponse,
)
from archcare.utils import (
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
    """
    Renders [TaskService][archcare.services.task_service.TaskService] results and errors
    to the terminal.

    One public method per CLI outcome (`render_run`, `render_status`, `render_list`) plus small
    static helpers for error and edge-case messages, so the CLI commands stay free of
    presentation logic.
    """

    def __init__(self, task_registry: TaskRegistry) -> None:
        """
        Initialize the presenter.

        Args:
            task_registry (TaskRegistry): Task registry from which the
                [TaskDetailFormatter][archcare.core.formatter.TaskDetailFormatter]
                class for each task is looked up.
        """
        self._task_registry = task_registry

    def render_run(
        self, response: TaskRunResponse, settings: AppSettings, verbose: bool = False
    ) -> None:
        """
        Renders the result of `archcare task run` to console.

        For `maintenance-check` runs, the full report is delegated to [MaintenanceCheckPresenter][]
        (unless `output_mode` is `'file'`, in which case only a pointer to the report directory is
        shown). In all cases, a summary panel with status, message, duration, and — when `verbose`
        — the task-specific details is printed.

        Args:
            response (TaskRunResponse): Run outcome from
                [TaskService.run_task][archcare.services.task_service.TaskService.run_task]
                (including interactivity of the invocation).
            settings (AppSettings): Application settings; used for the maintenance-check
                `output_mode`, `require_acknowledgment`, and `report_dir`.
            verbose (bool): Whether to include the task-specific details (rendered via the task's
                registered formatter). Defaults to `False`.

        Side Effects:
            Prints to the terminal; for interactive maintenance-check runs with
                `require_acknowledgment`, may also prompt and wait for user acknowledgment.
        """
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
                print_info(f"Output mode was set to 'file', check the report in {report_dir}")
        console.print()

        # Render the task panel
        panel_content = self._format_task_details(response.task_name, response.outcome, verbose)
        print_panel(
            title=f"Task Result: {response.task_name}",
            content=panel_content,
            border_style="cyan",
        )

    def render_status(self, response: TaskStatusResponse) -> None:
        """
        Renders the result of `archcare task status` to console.

        Prints a schedule table (overdue / due / OK per task), followed by a summary panel with
        maintenance counts when a summary is present. When `due_only` filtering yields no tasks,
        prints a friendly success message instead of an empty table.

        Args:
            response (TaskStatusResponse): Status outcome from
                [TaskService.get_task_status][archcare.services.task_service.TaskService.get_task_status]
                (schedule info entries, optional summary, `due_only` flag).
        """

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
        """
        Print the task schedule table with color-coded statuses.

        Each task is rendered with a status glyph and colored due-date text: red `✗ DUE` when
        overdue, yellow `⚠ DUE` when due but not overdue, green `✓ OK` otherwise. Tasks never run
        show a dimmed `Never` for last run.

        Args:
            response (TaskStatusResponse): Schedule info entries to render.
        """
        # Build the data in the Presenter
        headers = ["Status", "Task", "Last Run", "Due"]
        rows: list[list[str | RenderableType]] = []

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

            last_run = info.last_run.strftime("%Y-%m-%d") if info.last_run else "[dim]Never[/dim]"
            rows.append([status, info.task_name, last_run, due_text])

        # Pass standard data to the generic UI primitive
        print_table(
            title="Task Schedule",
            headers=headers,
            rows=rows,
            justify=["center", "left", "right", "right"],
        )

    @staticmethod
    def render_list(response: TaskListResponse) -> None:
        """
        Renders the result of `archcare task list` to console.

        Prints each task as an entry line with an enabled (`✓`) / disabled (`✗`) glyph, type badge,
        and frequency, followed by its indented description. Prints a warning when the (possibly
        filtered) task set is empty.

        Args:
            response (TaskListResponse): Task listing from
                [TaskService.list_tasks][archcare.services.task_service.TaskService.list_tasks].
        """
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
        """
        Render a "task not found" error with a hint to list tasks.

        Args:
            task_name (str): The unknown task name from the request.
        """
        print_error(f"Task not found: {task_name}")
        print_info("Use 'archcare task list' to see available tasks")

    @staticmethod
    def empty() -> None:
        """
        Render an error for an empty/invalid tasks file.

        Includes recovery hints: check the logs, and run `archcare setup config` if archcare
        isn't initialized yet.
        """
        print_error("Tasks file is empty or invalid.")
        print_info("See the logs for more details.")
        print_info(
            "If archcare isn't initialized, run 'archcare setup config' to "
            "create a new configuration or add tasks manually."
        )

    @staticmethod
    def invalid_task_type() -> None:
        """Render an error for an invalid `--type` filter value."""
        print_error("Type must be 'automated' or 'manual'")

    @staticmethod
    def error(message: str) -> None:
        """
        Render an arbitrary error message.

        Args:
            message (str): The error text to display.
        """
        print_error(message)

    @staticmethod
    def aborted(task_name: str) -> None:
        """
        Render a warning that a task run was aborted by the user.

        Args:
            task_name (str): Name of the aborted task.
        """
        console.print()
        print_warning(f"Task '{task_name}' execution aborted")

    @staticmethod
    def _get_status_text(status: TaskStatus) -> str:
        """
        Map a TaskStatus to stylized Rich text.

        Args:
            status (TaskStatus): Final task status to render.

        Returns:
            (str): Rich markup string with a status glyph:

                - SUCCESS: green `✓ SUCCESS`
                - FAILURE: red `⨯ FAILURE`
                - PARTIAL: yellow `⚠ PARTIAL`
                - SKIPPED: blue `⤳ SKIPPED`
        """
        match status:
            case TaskStatus.SUCCESS:
                return "[green]✓ SUCCESS[/green]"
            case TaskStatus.FAILURE:
                return "[red]⨯ FAILURE[/red]"
            case TaskStatus.PARTIAL:
                return "[yellow]⚠ PARTIAL[/yellow]"
            case _:  # SKIPPED
                return "[blue]⤳ SKIPPED[/blue]"

    def _format_task_details(self, task_name: str, result: TaskResult, verbose: bool) -> str:
        """
        Build the summary panel content for a task run.

        Assembles the universal outer shell (status, message, duration, and error if present), and
        — in verbose mode — appends the task's domain-specific details rendered via its registered
        `TaskDetailFormatter` from the `TaskRegistry`.

        Args:
            task_name (str): Name of the executed task; used to look up its formatter class in
                the registry.
            result (TaskResult): The run outcome to summarize.
            verbose (bool): Whether to append the task-specific details.

        Returns:
            (str): Rich-markup text ready to be placed inside the result panel.
        """
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
