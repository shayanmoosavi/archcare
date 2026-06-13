"""One-time setup Typer commands for Archcare."""

from os import getenv
from pathlib import Path

import typer
from loguru import logger

from archcare.cli._state import get_executor
from archcare.config import create_default_config_files
from archcare.services.systemd import (
    generate_systemd_templates,
    install_systemd_templates,
    reload_systemd,
    setup_systemd_timer,
)
from archcare.utils import is_root
from archcare.utils.output import (
    print_header,
    print_info,
    print_warning,
    print_success,
    print_error,
    console,
)

setup_app = typer.Typer(help="One-time setup commands for bootstrapping Archcare.")


@setup_app.command("config")
def setup_config():
    """
    Initialize archcare configuration files.

    This creates default configuration files if they don't exist.
    """
    config_dir = Path.home() / ".config/archcare"

    print_header("Initializing Archcare")
    print_info(f"Config directory: {config_dir}")

    if config_dir.exists():
        files = list(config_dir.glob("*.toml"))
        if files:
            print_warning("Configuration files already exist:")
            for f in files:
                print(f"  - {f.name}")

            if not typer.confirm("Overwrite existing files?"):
                print_info("Initialization cancelled")
                raise typer.Exit(0)

    # Create config files
    create_default_config_files(config_dir)

    print_success("Configuration initialized!")
    print_info(f"Edit config files in: {config_dir}")
    print_info("Run 'archcare task list' to see available tasks")


@setup_app.command("timers")
def setup_timers(
    enable: bool = typer.Option(
        True, "--enable/--no-enable", help="Enable timers after installation"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be done without doing it"
    ),
):
    """
    Set up systemd timers for automated task execution.

    This command:
    - Creates systemd service and timer templates
    - Installs them to /etc/systemd/system/
    - Optionally enables specified timers

    Example:
        archcare setup timers --dry-run
        archcare setup timers
    """
    from pathlib import Path

    # Check root privilege
    if not is_root():
        print_error("This command needs root privilege and should be run with sudo.")
        raise typer.Exit(1)

    # Get username (sudo command sets SUDO_USER env variable)
    user = getenv("SUDO_USER")
    if not user:
        # Technically shouldn't happen since we check for root, but just in case
        print_error("Could not determine the user. Make sure to run with sudo.")
        raise typer.Exit(1)

    # Get user's home directory
    import pwd

    try:
        user_info = pwd.getpwnam(user)
        home_dir = user_info.pw_dir
    except KeyError:
        print_error(f"User '{user}' does not exist")
        raise typer.Exit(1)

    # Define systemd directory
    systemd_dir = Path("/etc/systemd/system")

    service_content, timer_content = generate_systemd_templates(home_dir, user)

    # Service and timer file paths
    service_file = systemd_dir / f"archcare@.service"
    timer_file = systemd_dir / f"archcare@.timer"

    try:
        # Load task configuration to show available tasks
        executor = get_executor(user)
        tasks_config = executor.config_loader.load_tasks()
        automated_tasks = tasks_config.get_tasks_by_type("automated")

        install_systemd_templates(
            dry_run, service_content, service_file, timer_content, timer_file
        )

        # Reload systemd
        print()
        reload_systemd(dry_run)

        console.print("\n" + "=" * 60, style="bold green")
        print_success("Systemd templates installed successfully!")
        console.print("=" * 60, style="bold green")

        if automated_tasks:
            setup_systemd_timer(automated_tasks, dry_run, enable)
        else:
            print()
            print_warning("No automated tasks found in configuration")
            print_info("Edit ~/.config/archcare/tasks.toml to configure tasks")

        print("\n" + "=" * 60)
        print("Useful Commands")
        print("=" * 60)
        print(f"\n# List all timers")
        print(f"  systemctl list-timers 'archcare@*'")
        print(f"\n# Check specific timer")
        print(f"  systemctl status archcare@TASK.timer")
        print(f"\n# View logs")
        print(f"  journalctl -u archcare@TASK.service")
        print(f"\n# Manually trigger")
        print(f"  sudo systemctl start archcare@TASK.service")
        print(f"\n# Disable timer")
        print(f"  sudo systemctl disable --now archcare@TASK.timer")

    except Exception as e:
        print_error(f"Setup failed: {e}")
        logger.exception("Setup error")
        raise typer.Exit(1)
