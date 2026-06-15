"""
Presenter for the `setup` command group.

Note: `archcare.services.systemd` (install_systemd_templates, reload_systemd,
setup_systemd_timer) already prints its own progress output - that is a
pre-existing pattern from before this refactor and is out of scope here.
This presenter covers everything that was previously printed directly by
the CLI commands themselves: headers, banners, and the final summary.
"""

from pathlib import Path

from archcare.services.responses import ConfigInitResponse
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
    def templates_installed() -> None:
        console.print("\n" + "=" * 60, style="bold green")
        print_success("Systemd templates installed successfully!")
        console.print("=" * 60, style="bold green")

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
