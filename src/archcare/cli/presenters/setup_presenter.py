"""
Presenter for the `setup` command group.

Owns all terminal rendering for the setup services
([`ConfigService`][archcare.services.setup_service.ConfigService] and
[`TimerService`][archcare.services.setup_service.TimerService]): configuration initialization
output, systemd template installation progress, timer setup results, follow-up command hints, and
error messages. All methods are static — the presenter is stateless.

See Also:
    - [`archcare.services.setup_service`][]: Producer of the responses and errors rendered here
    - [`archcare.cli.presenters.task_presenter`][]: Renderer for the `task` command group
"""

from pathlib import Path

from archcare.services.responses import (
    ConfigInitResponse,
    InstallTemplatesResponse,
    ReloadSystemdResponse,
    TimerSetupResponse,
)
from archcare.utils import (
    console,
    print_error,
    print_header,
    print_info,
    print_success,
    print_warning,
)


class SetupPresenter:
    """
    Renders setup-related results and errors to the terminal.

    Grouped by command: `setup config` (header, existing-file warning, initialization results) and
    `setup timers` (template installation, daemon reload, timer enabling, follow-up hints), plus
    shared error renderers. Dry-run responses are rendered with "Would ..." phrasing so the user can
    distinguish planned from applied actions.
    """

    # -- setup config -----------------------------------------------------

    @staticmethod
    def config_header(config_dir: Path) -> None:
        """
        Print the header for `archcare setup config`.

        Args:
            config_dir (Path): Configuration directory that will be initialized.
        """
        print_header("Initializing Archcare")
        print_info(f"Config directory: {config_dir}")

    @staticmethod
    def existing_files_warning(files: list[Path]) -> None:
        """
        Warn that configuration files already exist.

        Typically shown before asking the user whether to overwrite them.

        Args:
            files (list[Path]): Existing TOML config files found in the config directory.
        """
        print_warning("Configuration files already exist:")
        for f in files:
            console.print(f"  - {f.name}")

    @staticmethod
    def render_config_init(response: ConfigInitResponse) -> None:
        """
        Render the result of `archcare setup config`.

        Lists created files (✔) and files skipped because they already existed, then prints
        next-step hints (config location, `task list`).

        Args:
            response (ConfigInitResponse): Initialization outcome from
                [`ConfigService.initialize`][archcare.services.setup_service.ConfigService.initialize].
        """
        if response.created_files:
            print_success("Configuration files created:")
            for f in response.created_files:
                console.print(f"  ✔ {f.name}")

        if response.skipped_files:
            print_info("Already present, left untouched:")
            for f in response.skipped_files:
                console.print(f"  - {f.name}")

        print_success("Configuration initialized!")
        print_info(f"Edit config files in: {response.config_dir}")
        print_info("Run 'archcare task list' to see available tasks")

    # -- setup timers -------------------------------------------------------

    @staticmethod
    def render_template_installation(response: InstallTemplatesResponse) -> None:
        """
        Render the installation of the systemd template units.

        Prints the target service and timer paths; in dry-run mode the actions are phrased as
        "Would create" instead of "Created".

        Args:
            response (InstallTemplatesResponse): Installation outcome from
                [`TimerService.install_templates`][archcare.services.setup_service.TimerService.install_templates].
        """
        verb = "Would create" if response.dry_run else "Created"
        print_info(f"Installing service template: {response.service_file}")
        print_success(f"  {verb} {response.service_file}")
        print_info(f"Installing timer template: {response.timer_file}")
        print_success(f"  {verb} {response.timer_file}")

    @staticmethod
    def render_systemd_reload(response: ReloadSystemdResponse) -> None:
        """
        Render the systemd daemon reload step.

        Args:
            response (ReloadSystemdResponse): Reload outcome from
                [`TimerService.reload`][archcare.services.setup_service.TimerService.reload];
                dry-run is phrased as "Would reload".
        """
        print_info("Reloading systemd daemon...")
        verb = "Would reload" if response.dry_run else "Reloaded"
        print_success(f"  {verb} systemd daemon")

    @staticmethod
    def templates_installed() -> None:
        """Print the success banner after all templates are installed."""
        console.print("\n" + "=" * 60, style="bold green")
        print_success("Systemd templates installed successfully!")
        console.print("=" * 60, style="bold green")

    @staticmethod
    def render_timer_setup(response: TimerSetupResponse) -> None:
        """
        Render the result of the timer setup flow.

        Lists the automated tasks found in configuration (with enabled status), prints manual enable
        instructions with an example derived from the first task, and — when timers were actually
        enabled — shows per-timer enable results and the `systemctl list-timers` status output.

        Args:
            response (TimerSetupResponse): Timer setup outcome from
                [`TimerService.setup_timers`][archcare.services.setup_service.TimerService.setup_timers].
        """
        console.print()
        print_info("Available automated tasks:")
        for task_name, task_config in response.automated_tasks.items():
            status_icon = "✔" if task_config.enabled else "✘"
            console.print(f"  {status_icon} {task_name}: {task_config.description}")

        console.print()
        print_info("To enable a timer:")
        console.print("  sudo systemctl enable --now archcare@TASK.timer\n")
        print_info("Example:")
        first_task = next(iter(response.automated_tasks.keys()))
        console.print(f"  sudo systemctl enable --now archcare@{first_task}.timer\n")

        if response.enabled_timers:
            console.print("\n" + "=" * 60, style="bold blue")
            print_info("Enabling timers for automated tasks...")
            console.print("=" * 60, style="bold blue")
            _list_timers(response)

        if response.timer_status:
            console.print("=" * 60, style="bold blue")
            print_info("Timer Status")
            console.print("=" * 60, style="bold blue")
            console.print(f"\n{response.timer_status}")

    @staticmethod
    def no_automated_tasks() -> None:
        """
        Warn that no automated tasks are configured.

        Points the user at `~/.config/archcare/tasks.toml` to add some.
        """
        console.print()
        print_warning("No automated tasks found in configuration")
        print_info("Edit ~/.config/archcare/tasks.toml to configure tasks")

    @staticmethod
    def useful_commands() -> None:
        """
        Print a cheat-sheet of useful systemd/journal commands.

        Covers listing archcare timers, checking a specific timer, viewing logs, manual triggering,
        and disabling timers.
        """
        console.print("\n" + "=" * 60)
        console.print("Useful Commands")
        console.print("=" * 60)
        console.print("\n[dim]# List all timers[/dim]")
        console.print("  systemctl list-timers 'archcare@*'")
        console.print("\n[dim]# Check specific timer[/dim]")
        console.print("  systemctl status archcare@TASK.timer")
        console.print("\n[dim]# View logs[/dim]")
        console.print("  journalctl -u archcare@TASK.service")
        console.print("\n[dim]# Manually trigger[/dim]")
        console.print("  sudo systemctl start archcare@TASK.service")
        console.print("\n[dim]# Disable timer[/dim]")
        console.print("  sudo systemctl disable --now archcare@TASK.timer")

    @staticmethod
    def dry_run_notice() -> None:
        """Print the dry-run completion notice with the apply hint."""
        console.print()
        print_success("Dry run complete - no changes were made. Remove --dry-run to apply changes.")

    # -- shared errors ------------------------------------------------------

    @staticmethod
    def not_root() -> None:
        """Render the error shown when `setup timers` runs without sudo."""
        print_error("This command needs root privilege and should be run with sudo.")

    @staticmethod
    def error(message: str) -> None:
        """
        Render an arbitrary error message.

        Args:
            message (str): The error text to display.
        """
        print_error(message)


def _list_timers(response: TimerSetupResponse):
    """
    Print the per-timer enable results.

    Args:
        response (TimerSetupResponse): Must contain non-empty `enabled_timers` (guaranteed by the
            only caller, `SetupPresenter.render_timer_setup`).
    """
    console.print()
    for timer in response.enabled_timers:
        print_info(f"Enabling {timer.timer_name}...")
        if timer.enabled:
            print_success(f"{timer.timer_name} enabled and started\n")
        else:
            print_warning(f"Failed to enable {timer.timer_name}\n")
