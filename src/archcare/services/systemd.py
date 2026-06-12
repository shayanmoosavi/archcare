"""Systemd service and timer management for Archcare."""

from pathlib import Path

import typer

from archcare.config import TaskConfig
from archcare.utils import run_systemctl
from archcare.utils.output import (
    console,
    print_info,
    print_success,
    print_warning,
    print_error,
)


def setup_systemd_timer(
    automated_tasks: dict[str, TaskConfig], dry_run: bool, enable: bool
):
    print()
    print_info("Available automated tasks:")
    for task_name, task_config in automated_tasks.items():
        task_status = "✓" if task_config.enabled else "✗"
        print(f"  {task_status} {task_name}: {task_config.description}")

    print()
    print_info("To enable a timer:")
    print(f"  sudo systemctl enable --now archcare@TASK.timer\n")
    print_info("Example:")
    first_task = next(iter(automated_tasks.keys()))
    print(f"  sudo systemctl enable --now archcare@{first_task}.timer\n")

    # Optionally enable timers
    if enable and not dry_run:
        _enable_systemd_timer(automated_tasks)

        # Show timer status
        console.print("=" * 60, style="bold blue")
        print_info("Timer Status")
        console.print("=" * 60, style="bold blue")
        result = run_systemctl(["list-timers", f"archcare@*"])
        if result.success:
            print(f"\n{result.stdout}")


def _enable_systemd_timer(automated_tasks: dict[str, TaskConfig]):
    console.print("\n" + "=" * 60, style="bold blue")
    print_info("Enabling timers for automated tasks...")
    console.print("=" * 60, style="bold blue")

    print()
    for task_name in automated_tasks.keys():
        timer_name = f"archcare@{task_name}.timer"
        print_info(f"Enabling {timer_name}...")

        result = run_systemctl(["enable", "--now", timer_name])
        if result.success:
            print_success(f"{timer_name} enabled and started\n")
        else:
            print_warning(f"Failed to enable {timer_name}\n")


def reload_systemd(dry_run: bool):
    print_info("Reloading systemd daemon...")
    if not dry_run:
        result = run_systemctl(["daemon-reload"])
        if not result.success:
            print_error("Failed to reload systemd")
            raise typer.Exit(1)
    print_success("  Systemd daemon reloaded")


def install_systemd_templates(
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


def generate_systemd_templates(home_dir: str, user: str) -> tuple[str, str]:
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
