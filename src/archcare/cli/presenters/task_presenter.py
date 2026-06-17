"""
Presenter for the `task` command group.

Owns all terminal rendering for TaskService results.
"""

from archcare.cli._state import get_settings
from archcare.cli.presenters.maintenance_presenter import MaintenanceCheckPresenter
from archcare.core.models import MaintenanceCheckResult
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
    print_schedule_table,
    print_success,
    print_summary_panel,
    print_task_details,
    print_task_result,
    print_warning,
)


class TaskPresenter:
    """Renders TaskService results and errors to the terminal."""

    @staticmethod
    def render_run(response: TaskRunResponse, verbose: bool = False) -> None:
        if not response.outcome.is_skipped():
            print_header(f"Running Task: {response.task_name}", response.is_interactive)

        # The maintenance-check task has this in TaskResult details dictionary
        maintenance_result: MaintenanceCheckResult | None = (
            response.outcome.details.get("maintenance_result")
        )

        # Maintenance issues table rendering
        if maintenance_result:
            settings = get_settings()
            report_dir = settings.report_dir
            mc_settings = settings.maintenance_check
            del settings

            # Do not render if output_mode = 'file'
            if mc_settings.output_mode != "file":
                MaintenanceCheckPresenter.render(
                    maintenance_result,
                    is_interactive=response.is_interactive,
                    require_acknowledgment=mc_settings.require_acknowledgment,
                )
            else:
                print_info(
                    f"Output mode was set to 'file', check the report in {report_dir}"
                )
        print()

        if verbose:
            print_task_details(
                response.task_name,
                response.outcome,
                show_details=True,
                is_interactive=response.is_interactive,
            )
        else:
            print_task_result(
                response.outcome, response.task_name, response.is_interactive
            )

    @staticmethod
    def render_status(response: TaskStatusResponse) -> None:

        if response.due_only and not response.schedule_info:
            print_success("No tasks currently due!")
            return

        print()
        print_schedule_table(response.schedule_info)

        if response.summary:
            print()
            print_summary_panel("Summary", response.summary)

    @staticmethod
    def render_list(response: TaskListResponse) -> None:
        print_header("Available Tasks")

        if not response.tasks:
            print_info("No tasks found")
            return

        for name, config in response.tasks.items():
            status_icon = "✓" if config.enabled else "✗"
            type_badge = f"[cyan]{config.task_type.value}[/cyan]"
            freq = f"every {config.frequency} days"

            console.print(f"{status_icon} [bold]{name}[/bold] {type_badge} ({freq})")
            console.print(f"  {config.description}")
            print()

    @staticmethod
    def not_found(task_name: str) -> None:
        print_error(f"Task not found: {task_name}")
        print_info("Use 'archcare task list' to see available tasks")

    @staticmethod
    def invalid_task_type() -> None:
        print_error("Type must be 'automated' or 'manual'")

    @staticmethod
    def error(message: str, is_interactive: bool = True) -> None:
        print_error(message, is_interactive)

    @staticmethod
    def aborted(task_name: str) -> None:
        print()
        print_warning(f"Task '{task_name}' execution aborted")
