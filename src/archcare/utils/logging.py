"""
Logging configuration for archcare.

Sets up loguru for structured logging to files.
"""

import sys

from loguru import logger

from archcare.config import AppSettings, LogLevel


def setup_logging(settings: AppSettings, reconfigure: bool = False) -> None:
    """
    Configure logging for archcare.

    Args:
        settings: Application settings with log configuration
        reconfigure: If True, remove existing handlers before adding new ones
    """
    # Remove default handler (stderr)
    logger.remove()

    # Add console handler (for CLI output)
    # Only show INFO and above in console
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
    )

    if reconfigure:
        logger.info(f"Logging reconfigured: {log_file}")
    else:
        logger.info(f"Logging configured: {log_file}")
    logger.debug(f"Log level: {settings.log_level.value}")


def setup_task_logging(task_name: str, settings: AppSettings) -> None:
    """
    Set up a separate log file for a specific task.

    Args:
        task_name: Name of the task
        settings: Application settings
    """
    task_log_dir = settings.log_dir / "tasks"
    task_log_dir.mkdir(parents=True, exist_ok=True)

    task_log_file = task_log_dir / f"{task_name}.log"

    logger.add(
        task_log_file,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        level="DEBUG",  # Always debug level for task logs
        rotation="5 MB",
        retention=f"{settings.log_retention_days} days",
        filter=lambda record: record["extra"].get("task") == task_name,
    )

    logger.debug(f"Task logging configured: {task_log_file}")


def get_task_logger(task_name: str):
    """
    Get a logger bound to a specific task.

    Args:
        task_name: Name of the task

    Returns:
        Logger instance bound to the task

    Example:
        task_logger = get_task_logger("system-update")
        task_logger.info("Starting system update...")
    """
    return logger.bind(task=task_name)
