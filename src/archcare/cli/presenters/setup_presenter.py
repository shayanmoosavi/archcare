"""
Presenter for the `setup` command group.

Note: `archcare.services.systemd` (install_systemd_templates, reload_systemd,
setup_systemd_timer) already prints its own progress output - that is a
pre-existing pattern from before this refactor and is out of scope here.
This presenter covers everything that was previously printed directly by
the CLI commands themselves: headers, banners, and the final summary.
"""

from pathlib import Path

from archcare.config import TaskConfig
from archcare.services.responses import (
    ConfigInitResponse,
    InstallTemplatesResponse,
    ReloadSystemdResponse,
    EnableTimersResponse,
)
from archcare.utils.output import (
    console,
    print_error,
    print_header,
    print_info,
    print_success,
    print_warning,
)


class SetupPresenter:
    """Renders setup-related results and errors to the terminal."""

    # -- setup config -----------------------------------------------------

    @staticmethod
    def config_header(config_dir: Path) -> None:
        print_header("Initializing Archcare")
        print_info(f"Config directory: {config_dir}")

    @staticmethod
    def existing_files_warning(files: list[Path]) -> None:
        print_warning("Configuration files already exist:")
        for f in files:
            print(f"  - {f.name}")

    @staticmethod
    def init_cancelled() -> None:
        print_info("Initialization cancelled")

    @staticmethod
    def render_config_init(response: ConfigInitResponse) -> None:
        print_success("Configuration initialized!")
        print_info(f"Edit config files in: {response.config_dir}")
        print_info("Run 'archcare task list' to see available tasks")

    # -- setup timers -------------------------------------------------------

    @staticmethod
    def render_template_installation(
        response: InstallTemplatesResponse, dry_run: bool
    ) -> None:
        verb = "Would create" if response.dry_run else "Created"
        print_info(f"Installing service template: {response.service_file}")
        print_success(f"  {verb} {response.service_file}")
        print_info(f"Installing timer template: {response.timer_file}")
        print_success(f"  {verb} {response.timer_file}")

    @staticmethod
    def render_systemd_reload(response: ReloadSystemdResponse, dry_run: bool) -> None:
        print_info("Reloading systemd daemon...")
        verb = "Would reload" if dry_run else "Reloaded"
        if not response.success:
            print_error("Failed to reload systemd")
            return
        print_success(f"  {verb} systemd daemon")

    @staticmethod
    def templates_installed() -> None:
        console.print("\n" + "=" * 60, style="bold green")
        print_success("Systemd templates installed successfully!")
        console.print("=" * 60, style="bold green")

    @staticmethod
    def render_timer_setup(
        automated_tasks: dict[str, TaskConfig],
        response: EnableTimersResponse,
        dry_run: bool,
        enable: bool,
    ) -> None:
        print()
        print_info("Available automated tasks:")
        for task_name, task_config in automated_tasks.items():
            task_status = "✓" if task_config.enabled else "✗"
            print(f"  {task_status} {task_name}: {task_config.description}")

        print()
        print_info("To enable a timer:")
        print("  sudo systemctl enable --now archcare@TASK.timer\n")

        if automated_tasks:
            first_task = next(iter(automated_tasks.keys()))
            print_info("Example:")
            print(f"  sudo systemctl enable --now archcare@{first_task}.timer\n")

        if enable and not dry_run:
            console.print("\n" + "=" * 60, style="bold blue")
            print_info("Enabling timers for automated tasks...")
            console.print("=" * 60, style="bold blue")
            print()

            _list_timers(response)

            if response.timer_status_output:
                console.print("=" * 60, style="bold blue")
                print_info("Timer Status")
                console.print("=" * 60, style="bold blue")
                print(f"\n{response.timer_status_output}")

    @staticmethod
    def no_automated_tasks() -> None:
        print()
        print_warning("No automated tasks found in configuration")
        print_info("Edit ~/.config/archcare/tasks.toml to configure tasks")

    @staticmethod
    def useful_commands() -> None:
        print("\n" + "=" * 60)
        print("Useful Commands")
        print("=" * 60)
        print("\n# List all timers")
        print("  systemctl list-timers 'archcare@*'")
        print("\n# Check specific timer")
        print("  systemctl status archcare@TASK.timer")
        print("\n# View logs")
        print("  journalctl -u archcare@TASK.service")
        print("\n# Manually trigger")
        print("  sudo systemctl start archcare@TASK.service")
        print("\n# Disable timer")
        print("  sudo systemctl disable --now archcare@TASK.timer")

    @staticmethod
    def dry_run_notice() -> None:
        print()
        print_success(
            "Dry run complete - no changes were made. Remove --dry-run to apply changes."
        )

    # -- shared errors ------------------------------------------------------

    @staticmethod
    def not_root() -> None:
        print_error("This command needs root privilege and should be run with sudo.")

    @staticmethod
    def error(message: str) -> None:
        print_error(message)


def _list_timers(response: EnableTimersResponse):
    for timer_name in response.enabled_timers:
        print_info(f"Enabling {timer_name}...")
        print_success(f"{timer_name} enabled and started\n")

    for timer_name in response.failed_timers:
        print_info(f"Enabling {timer_name}...")
        print_warning(f"Failed to enable {timer_name}\n")
