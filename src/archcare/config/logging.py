"""
Logging configuration for Archcare.

Configures `loguru` for structured, rotating file logging with optional console
mirroring for development. Manages both global application logs and per-task
log files with automatic ownership handling for systemd timer execution.

Key responsibilities:
    - Initialize global log file with rotation, retention, and compression
    - Create per-task log files filtered by task name
    - Handle file ownership when running as root via systemd
    - Respect log level and retention settings from `AppSettings`

Configuration (via `AppSettings`):
    - `log_level`: Minimum level for global log file (default: INFO)
    - `log_retention_days`: Days to retain rotated logs (default: 30)
    - `log_dir`: Base directory for log files (default: `~/.local/state/archcare/logs`)

See Also:
    - [AppSettings][]: Logging configuration fields
    - [LogLevel][]: Supported log levels
    - [UserContext][archcare.utils.UserContext]: File ownership handling
    - [TaskExecutor][archcare.core.executor.TaskExecutor]: Calls setup_task_logging per task
"""

import sys

from loguru import logger

from archcare.utils import UserContext

from .models import AppSettings, LogLevel


def setup_logging(
    settings: AppSettings, reconfigure: bool = False, devel_mode: bool = False
) -> None:
    """
    Configure global logging for the application.

    Removes any existing loguru handlers and installs new ones based on
    `settings`. Creates the log directory if needed. In development mode,
    adds a colorized console handler mirroring INFO+ messages to stderr.

    Args:
        settings (AppSettings): Application settings containing log level,
            retention, and log directory.
        reconfigure (bool): If True, indicates logging is being reconfigured
            (e.g., after settings change). Affects the startup log message.
            Defaults to False.
        devel_mode (bool): If True, add a colorized console handler for
            development. Defaults to False.

    Raises:
        OSError: If the log directory cannot be created or files cannot be
            written.
        PermissionError: If ownership change fails when running as root.

    Side Effects:
        - Mutates global `loguru.logger` handlers
        - Creates `settings.log_dir` and log files
        - May change file ownership via `UserContext.chown_if_root`

    See Also:
        - [setup_task_logging][]: Configure per-task logging
        - [AppSettings.log_dir][]: Property for log directory setting
        - [AppSettings][]: The `log_level` attribute
        - [UserContext.chown_if_root][archcare.utils.UserContext.chown_if_root]: Ownership handling
    """
    # Remove default handler (stderr)
    logger.remove()

    # Add console handler (for CLI output)
    # Only show INFO and above in console
    if devel_mode:
        logger.add(
            sys.stderr,
            format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
            "<level>{message}</level>",
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
    UserContext.from_env().chown_if_root(settings.log_dir, log_file)


def setup_task_logging(task_name: str, settings: AppSettings) -> int:
    """
    Configure a dedicated log file for a specific task.

    Creates a task-specific log file under `settings.log_dir/tasks/` with a
    loguru filter that only captures records where `record["extra"]["task"]`
    matches `task_name`. Always uses DEBUG level for task logs regardless of
    global log level.

    Args:
        task_name (str): Name of the task (e.g., "failed-services",
            "health-check"). Used for the log filename and filter.
        settings (AppSettings): Application settings for log directory and
            retention policy.

    Returns:
        int: The loguru handler ID. Pass to `logger.remove(handler_id)` to
            stop task logging (used in `BaseTask.run`).

    Raises:
        OSError: If the task log directory cannot be created or file cannot
            be written.
        PermissionError: If ownership change fails when running as root.

    Side Effects:
        - Adds a filtered handler to global `loguru.logger`
        - Creates `settings.log_dir/tasks/` directory
        - May change file ownership via `UserContext.chown_if_root`

    See Also:
        - [setup_logging][]: Configure global logging
        - [BaseTask.run][archcare.tasks.base.BaseTask.run]: Adds task context to log records
        - [UserContext.chown_if_root][archcare.utils.UserContext.chown_if_root]: Ownership handling
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
    UserContext.from_env().chown_if_root(task_log_dir, task_log_file)

    return handler_id
