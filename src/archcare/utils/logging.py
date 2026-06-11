"""
Logging configuration for archcare.

Sets up loguru for structured logging to files.
"""

import os
import sys

from loguru import logger

from archcare.config import AppSettings, LogLevel

from .system import is_root, change_ownership_to_user


def setup_logging(
    settings: AppSettings, reconfigure: bool = False, devel_mode: bool = False
) -> None:
    """
    Configure logging for archcare.

    Args:
        settings: Application settings with log configuration
        reconfigure: If True, remove existing handlers before adding new ones
        devel_mode: If True, mirror the logs to the console for development
    """
    # Remove default handler (stderr)
    logger.remove()

    # Add console handler (for CLI output)
    # Only show INFO and above in console
    if devel_mode:
        logger.add(
            sys.stderr,
            format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
            level=LogLevel.INFO.value,
            colorize=True,
        )

    # Ensure log directory exists
    settings.log_dir.mkdir(parents=True, exist_ok=True)

    # Add file handler (detailed logs)
    log_file = settings.log_dir / "archcare.log"
    logger.add(
        log_file,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
        level=settings.log_level.value,
        rotation="10 MB",  # Rotate when file reaches 10MB
        retention=f"{settings.log_retention_days} days",
        compression="gz",  # Compress rotated logs
        enqueue=True,  # Thread-safe
    )

    if reconfigure:
        logger.info(f"Logging reconfigured: {log_file}")
    else:
        logger.info(f"Logging configured: {log_file}")
    logger.debug(f"Log level: {settings.log_level.value}")

    # Change ownership if running as root via systemd
    user = os.environ.get("ARCHCARE_USER")
    if is_root() and user:
        change_ownership_to_user(settings.log_dir, user)
        change_ownership_to_user(log_file, user)


def setup_task_logging(task_name: str, settings: AppSettings) -> int:
    """
    Set up a separate log file for a specific task.

    Args:
        task_name: Name of the task
        settings: Application settings
    """
    task_log_dir = settings.log_dir / "tasks"
    task_log_dir.mkdir(parents=True, exist_ok=True)

    task_log_file = task_log_dir / f"{task_name}.log"

    handler_id = logger.add(
        task_log_file,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        level=LogLevel.DEBUG.value,  # Always debug level for task logs
        rotation="5 MB",
        retention=f"{settings.log_retention_days} days",
        compression="gz",
        enqueue=True,
        filter=lambda record: record["extra"].get("task") == task_name,
    )

    logger.info(f"Task logging configured: {task_log_file}")

    # Change ownership if running as root via systemd
    user = os.environ.get("ARCHCARE_USER")
    if is_root() and user:
        change_ownership_to_user(task_log_dir, user)
        change_ownership_to_user(task_log_file, user)

    return handler_id
