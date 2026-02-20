"""
Command-line interface for archcare.

Provides commands for running maintenance tasks and viewing status.
"""

import os
from pathlib import Path
from typing import Any

import typer
from loguru import logger

from archcare.config import (
    AppSettings,
    ConfigLoader,
    create_default_config_files,
    TasksConfig,
    TaskConfig,
    TaskType,
)
from archcare.core import TaskExecutor, TaskScheduler
from archcare.tasks import (
    BaseTask,
    FailedServicesTask,
    HealthCheckTask,
    MaintenanceCheckTask,
    MirrorlistUpdateTask,
)
from archcare.utils import run_systemctl, is_root, NotificationUrgency, NotificationIcon
from archcare.utils.output import (
    print_error,
    print_header,
    print_info,
    print_schedule_table,
    print_success,
    print_summary_panel,
    print_task_details,
    print_task_result,
    print_warning,
    console,
)
from archcare.utils.logging import setup_logging

# Create Typer app
app = typer.Typer(
    name="archcare",
    help="Arch Linux maintenance task manager",
)

# Global state (initialized in main)
_loader: ConfigLoader | None = None
_settings: AppSettings | None = None
_executor: TaskExecutor | None = None


def get_executor(user: str | None = None) -> TaskExecutor:
    """
    Get or create the task executor.

    Returns:
        TaskExecutor instance
    """
    global _loader, _settings, _executor

    if not _executor:

        # Set up default logging first
        default_settings = AppSettings(user=user)
        default_settings.ensure_directories()
        setup_logging(default_settings)

        # Initialize configuration
        if not _loader:
            _loader = ConfigLoader(user=user)

        if not _settings:
            _settings = _loader.load_settings()

            # Reconfigure logging with user's custom settings if they differ
            # Check if any logging-related settings changed
            if (
                _settings.log_dir != default_settings.log_dir
                or _settings.log_level != default_settings.log_level
                or _settings.log_retention_days != default_settings.log_retention_days
            ):
                setup_logging(_settings, reconfigure=True)

        # Load state
        state = _loader.load_state()

        # Create executor
        _executor = TaskExecutor(
            config_loader=_loader,
            settings=_settings,
            state=state,
        )

        # Register all available tasks
        _register_tasks(_executor)

    return _executor


def _register_tasks(executor: TaskExecutor) -> None:
    """
    Register all available task implementations.

    Args:
        executor: TaskExecutor to register tasks with
    """
    tasks_mapping: dict[str, type[BaseTask]] = {
        "failed-services": FailedServicesTask,
        "check-health": HealthCheckTask,
        "update-mirrorlist": MirrorlistUpdateTask,
        "check-maintenance": MaintenanceCheckTask,
    }

    for command, task_class in tasks_mapping.items():
        executor.register_task(command, task_class)


def _validate_task_name(task_name: str, tasks_config: TasksConfig):
    try:
        tasks_config.get_task(task_name)
    except ValueError:
        print_error(f"Task not found: {task_name}")
        print_info("Use 'archcare list' to see available tasks")
        raise typer.Exit(1)


@app.command()
def run(
    task_name: str = typer.Argument(help="Name of the task to run"),
    force: bool = typer.Option(False, "--force", "-f", help="Run even if not due"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
):
    """
    Run a specific maintenance task.

    Example:
        archcare run failed-services
        archcare run system-update --force
    """
    user = os.environ.get("ARCHCARE_USER")
    executor = get_executor(user)

    print_header(f"Running Task: {task_name}")

    try:
        # Check if task exists in configuration
        tasks_config = executor.config_loader.load_tasks()

        _validate_task_name(task_name, tasks_config)

        # Execute the task
        logger.info(f"Executing task: {task_name}")
        result = executor.execute_task(task_name, force)

        # Display result
        print()
        if verbose:
            print_task_details(task_name, result, show_details=True)
        else:
            print_task_result(result, task_name)

        # Exit code based on result
        if result.is_success():
            raise typer.Exit(0)
        elif result.is_partial():
            # Partial success - found issues but task completed
            raise typer.Exit(0)
        elif result.is_skipped():
            raise typer.Exit(0)
        else:  # FAILED
            raise typer.Exit(1)

    except typer.Exit as e:
        if e.exit_code != 0:
            raise

    except Exception as e:
        print_error(f"Failed to run task: {e}")
        logger.exception(f"Error running task {task_name}")
        raise typer.Exit(1)


@app.command()
def status(
    task_name: str | None = typer.Argument(None, help="Specific task to check"),
    due_only: bool = typer.Option(False, "--due", help="Show only due tasks"),
):
    """
    Show status and schedule for tasks.

    Example:
        archcare status                    # All tasks
        archcare status failed-services    # Specific task
        archcare status --due              # Only due tasks
    """
    executor = get_executor()
    tasks_config = executor.config_loader.load_tasks()
    scheduler = TaskScheduler(tasks_config, executor.state)

    if task_name:
        # Show specific task
        print_header(f"Task Status: {task_name}")

        try:
            info = scheduler.get_schedule_info(task_name)
            print_schedule_table([info])
        except ValueError as e:
            print_error(str(e))
            raise typer.Exit(1)

    else:
        # Show all tasks or just due tasks
        print_header("Task Status")

        if due_only:
            schedule_info = scheduler.get_due_tasks()
            if not schedule_info:
                print_success("No tasks currently due!")
                raise typer.Exit(0)
        else:
            schedule_info = scheduler.get_all_schedule_info()

        print_schedule_table(schedule_info)

        # Show summary
        summary = scheduler.get_maintenance_summary()
        print()
        print_summary_panel("Summary", summary)


@app.command("list")
def list_(
    task_type: str | None = typer.Option(
        None, "--type", "-t", help="Filter by type: automated or manual"
    ),
):
    """
    List all available tasks.

    Example:
        archcare list
        archcare list --type manual
    """
    executor = get_executor()
    tasks_config = executor.config_loader.load_tasks()

    print_header("Available Tasks")

    # Get tasks
    tasks = {}
    match task_type:
        case TaskType.AUTOMATED.value:
            tasks = tasks_config.get_tasks_by_type("automated")
        case TaskType.MANUAL.value:
            tasks = tasks_config.get_tasks_by_type("manual")
        case None:
            tasks = tasks_config.tasks
        case _:
            print_error("Type must be 'automated' or 'manual'")
            raise typer.Exit(1)

    if not tasks:
        print_info("No tasks found")
        raise typer.Exit(0)

    # Display tasks
    for name, config in tasks.items():
        status_icon = "✓" if config.enabled else "✗"
        type_badge = f"[cyan]{config.task_type.value}[/cyan]"
        freq = f"every {config.frequency} days"

        console.print(f"{status_icon} [bold]{name}[/bold] {type_badge} ({freq})")
        console.print(f"  {config.description}")
        print()


@app.command()
def init():
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
    print_info("Run 'archcare list' to see available tasks")


@app.command()
def setup(
    user: str | None = typer.Option(
        None, "--user", "-u", help="Username ([bold red]Required[/bold red])"
    ),
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
        archcare setup --dry-run --user YOUR_USERNAME
        archcare setup --user YOUR_USERNAME
    """
    from pathlib import Path

    # Check root privilege
    if not is_root():
        print_error("This command needs root privilege and should be run with sudo.")
        raise typer.Exit(1)

    # Get username
    if not user:
        print_error(
            "Username must be provided. Please specify with --user YOUR_USERNAME"
        )
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

    service_content, timer_content = _generate_systemd_templates(home_dir, user)

    # Service and timer file paths
    service_file = systemd_dir / f"archcare@.service"
    timer_file = systemd_dir / f"archcare@.timer"

    try:
        # Load task configuration to show available tasks
        executor = get_executor(user)
        tasks_config = executor.config_loader.load_tasks()
        automated_tasks = tasks_config.get_tasks_by_type("automated")

        _install_systemd_templates(
            dry_run, service_content, service_file, timer_content, timer_file
        )

        # Reload systemd
        _reload_systemd(dry_run)

        print_success("\n" + "=" * 60)
        print_success("Systemd templates installed successfully!")
        print_success("=" * 60)

        if automated_tasks:
            _setup_systemd_timer(automated_tasks, dry_run, enable)
        else:
            print_warning("\nNo automated tasks found in configuration")
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


def _setup_systemd_timer(
    automated_tasks: dict[str, TaskConfig], dry_run: bool, enable: bool
):
    print_info("\nAvailable automated tasks:")
    for task_name, task_config in automated_tasks.items():
        task_status = "✓" if task_config.enabled else "✗"
        print_info(f"  {task_status} {task_name}: {task_config.description}")

    print_info("\nTo enable a timer:")
    print_info(f"  sudo systemctl enable --now archcare@TASK.timer")
    print_info("\nExample:")
    first_task = next(iter(automated_tasks.keys()))
    print_info(f"  sudo systemctl enable --now archcare@{first_task}.timer")

    # Optionally enable timers
    if enable and not dry_run:
        _enable_systemd_timer(automated_tasks)

        # Show timer status
        print_info("\n" + "=" * 60)
        print_info("Timer Status")
        print_info("=" * 60)
        result = run_systemctl(["list-timers", f"archcare@*"])
        if result.success:
            print(result.stdout)


def _enable_systemd_timer(automated_tasks: dict[str, TaskConfig]):
    print_info("\n" + "=" * 60)
    print_info("Enabling timers for automated tasks...")
    print_info("=" * 60)

    for task_name in automated_tasks.keys():
        timer_name = f"archcare@{task_name}.timer"
        print_info(f"\nEnabling {timer_name}...")

        result = run_systemctl(["enable", "--now", timer_name])
        if result.success:
            print_success(f"  ✓ {timer_name} enabled and started")
        else:
            print_warning(f"  ✗ Failed to enable {timer_name}")


def _reload_systemd(dry_run: bool):
    print_info("\nReloading systemd daemon...")
    if not dry_run:
        result = run_systemctl(["daemon-reload"])
        if not result.success:
            print_error("Failed to reload systemd")
            raise typer.Exit(1)
    print_success("  Systemd daemon reloaded")


def _install_systemd_templates(
    dry_run: bool,
    service_content: str,
    service_file: Path,
    timer_content: str,
    timer_file: Path,
):
    # Install service template
    print_info(f"Installing service template: {service_file}")
    if not dry_run:
        service_file.write_text(service_content)
        service_file.chmod(0o644)
    print_success(f"  Created {service_file}")

    # Install timer template
    print_info(f"Installing timer template: {timer_file}")
    if not dry_run:
        timer_file.write_text(timer_content)
        timer_file.chmod(0o644)
    print_success(f"  Created {timer_file}")


def _generate_systemd_templates(home_dir: str, user: str) -> tuple[str, str]:
    # Service template content
    service_content = f"""[Unit]
Description=Archcare maintenance task: %i
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=root
Environment="ARCHCARE_USER={user}"

# Working directory
WorkingDirectory={home_dir}

# Run the task
ExecStart={home_dir}/.local/bin/archcare run %i

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=archcare-%i

# Security hardening
PrivateTmp=yes
NoNewPrivileges=yes
ProtectSystem=strict

# Allow access to necessary paths
ReadWritePaths={home_dir}/.config/archcare {home_dir}/.local/state/archcare /etc/pacman.d

# Resource limits
CPUQuota=50%
MemoryMax=1G
TimeoutStartSec=30min

# Don't restart on failure
Restart=no

[Install]
WantedBy=multi-user.target
"""
    # Timer template content
    timer_content = f"""[Unit]
Description=Archcare maintenance timer: %i
Requires=archcare@%i.service

[Timer]
# Default schedule (override per-task with drop-ins)
OnCalendar=daily

# Run if missed while system was off
Persistent=yes

# Randomize start time to avoid load spikes
RandomizedDelaySec=1h

# Accuracy (can wake from suspend)
AccuracySec=12h

[Install]
WantedBy=timers.target
"""
    return service_content, timer_content


@app.command()
def logs(
    task_name: str | None = typer.Argument(None, help="Task to show logs for"),
    lines: int = typer.Option(50, "--lines", "-n", help="Number of lines to show"),
):
    """
    Show logs for archcare or a specific task.

    Example:
        archcare logs                    # Main logs
        archcare logs failed-services    # Task-specific logs
    """
    executor = get_executor()

    if task_name:
        # Show task logs
        log_file = executor.settings.log_dir / "tasks" / f"{task_name}.log"
    else:
        # Show main logs
        log_file = executor.settings.log_dir / "archcare.log"

    if not log_file.exists():
        print_error(f"Log file not found: {log_file}")
        raise typer.Exit(1)

    print_header(f"Logs: {log_file.name}")

    # Read last N lines
    with open(log_file, "r") as f:
        all_lines = f.readlines()
        recent_lines = all_lines[-lines:]

    for line in recent_lines:
        print(line.rstrip())


@app.command()
def test_notification(
    severity: str = typer.Option(
        "warning",
        "--severity",
        "-s",
        help="Notification severity: critical, warning, or info",
    ),
):
    """
    Test desktop notifications.

    Sends a test notification to verify the notification system is working.

    Example:
        archcare test-notification
        archcare test-notification --severity critical
    """
    from archcare.utils import (
        send_notification,
        is_notification_available,
    )

    # Validate severity
    valid_severities = ["critical", "warning", "info"]
    severity_config: dict[str, Any] = {}
    match severity:
        case "critical":
            severity_config = {
                "urgency": NotificationUrgency.CRITICAL,
                "icon": NotificationIcon.ERROR,
                "title": "Testing severity `critical`",
            }
        case "warning":
            severity_config = {
                "urgency": NotificationUrgency.NORMAL,
                "icon": NotificationIcon.WARNING,
                "title": "Testing severity `warning`",
            }
        case "info":
            severity_config = {
                "urgency": NotificationUrgency.LOW,
                "icon": NotificationIcon.INFO,
                "title": "Testing severity `info`",
            }
        case _:
            print_error(f"Invalid severity: {severity}")
            print_info(f"Valid options: {', '.join(valid_severities)}")
            raise typer.Exit(1)

    # Setup default logging
    default_settings = AppSettings()
    default_settings.ensure_directories()
    setup_logging(default_settings)

    print_header("Testing Desktop Notifications")

    # Check if notifications are available
    if not is_notification_available():
        print_error("Desktop notifications are not available on this system")
        print_info("Install libnotify package to enable notifications:")
        print_info("  sudo pacman -S libnotify")
        raise typer.Exit(1)

    print_success("notify-send is available")

    # Send test notification
    print_info(f"Sending test notification with severity: {severity}")

    success = send_notification(
        title=severity_config["title"],
        message="This is a test notification from archcare.\nNotifications are working correctly!",
        urgency=severity_config["urgency"],
        icon=severity_config["icon"],
    )

    if success:
        print_success("Test notification sent successfully!")
        print_info("Check your notification area to see if it appeared")
    else:
        print_error("Failed to send notification")
        print_info("Check the logs for more details:")
        print_info("  archcare logs")
        raise typer.Exit(1)


def main():
    """
    Main entry point for the CLI.
    """
    app()


if __name__ == "__main__":
    main()
