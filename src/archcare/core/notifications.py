"""
Desktop notification manager for the Archcare application.

This module provides [NotificationManager][], which orchestrates sending desktop alerts using
the system's standard `notify-send` CLI tool (part of `libnotify`). It manages standardized urgency
levels via [NotificationUrgency][] and visual styles using [NotificationIcon][].

The system automatically detects if `notify-send` is available at runtime. If not,
notifications are gracefully disabled, and warning messages are directed to standard logging.
This ensures the core execution engine functions correctly in non-graphical environments,
such as systemd timers running as root, SSH sessions, or unit testing suites.

Key Concepts:
    - **Availability Check**: Availability is verified on initialization.
    - **Severity Mapping**: System maintenance alerts automatically map core [IssueSeverity][]
      values to corresponding [NotificationUrgency][] and standard
      desktop [NotificationIcon][] states.
    - **Robust Error Isolation**: Commands are wrapped with timeouts to prevent hanging during
      DBus/X11 environment mismatches.

See Also:
    - [archcare.utils.system][]: For subprocess wrapper execution.
    - [archcare.core.interaction][]: The user interaction port.
"""

import subprocess
from enum import Enum
from typing import Any

from loguru import logger

from archcare.utils import check_command_exists, run_command

from .models import IssueSeverity


class NotificationUrgency(Enum):
    """
    Urgency levels for desktop notifications.

    Corresponds to the `--urgency` flag supported by standard `notify-send` implementations.

    Attributes:
        LOW (str): Low priority notification. Typically used for routine, successful tasks.
        NORMAL (str): Default urgency. Used for standard warnings and normal execution tasks.
        CRITICAL (str): High urgency. Usually bypasses standard notification filters, remaining on
            screen until dismissed. Used for critical errors or urgent maintenance alerts.
    """

    LOW = "low"
    NORMAL = "normal"
    CRITICAL = "critical"

    def __str__(self) -> str:
        """
        Return the low-level string representation for the `notify-send` CLI option.

        Returns:
            str: One of `'low'`, `'normal'`, or `'critical'`.

        Examples:
            >>> from archcare.core.notifications import NotificationUrgency
            >>> str(NotificationUrgency.CRITICAL)
            'critical'
        """
        return self.value


class NotificationIcon(Enum):
    """
    Standard [freedesktop.org](https://freedesktop.org) icon names for desktop notifications.

    Provides a standard set of stock icon names commonly available across modern
    Linux desktop environments (such as GNOME, KDE Plasma, and XFCE).

    Attributes:
        INFO (str): Standard informational icon (`'dialog-information'`).
        WARNING (str): Standard warning alert icon (`'dialog-warning'`).
        ERROR (str): Standard critical error icon (`'dialog-error'`).
        SUCCESS (str): Standard validation success checkmark icon (`'emblem-default'`).
        MAINTENANCE (str): Standard system maintenance or software update icon
            (`'system-software-update'`).
    """

    INFO = "dialog-information"
    WARNING = "dialog-warning"
    ERROR = "dialog-error"
    SUCCESS = "emblem-default"
    MAINTENANCE = "system-software-update"

    def __str__(self) -> str:
        """
        Return the low-level [freedesktop.org](https://freedesktop.org) theme icon name string.

        Returns:
            str: The icon string name.

        Examples:
            >>> from archcare.core.notifications import NotificationIcon
            >>> str(NotificationIcon.SUCCESS)
            'emblem-default'
        """
        return self.value


class NotificationManager:
    """
    Manages desktop notifications using notify-send.

    The manager handles initializing the notification connection check, logging fallback
    warnings when `notify-send` command is not available, formatting and executing
    notification subprocess invocations with timeouts, and mapping application alerts to
    appropriate urgency states.

    Examples:
        >>> from archcare.core.notifications import NotificationManager
        >>> manager = NotificationManager()
        >>> # Verify if desktop notifications can be sent on this platform
        >>> status = manager.is_available()
        >>> # Check for returned type rather than actual value to ensure predictable outcome
        >>> isinstance(status, bool)
        True

    See Also:
        - [NotificationUrgency][]: Defines standard urgency levels.
        - [NotificationIcon][]: Defines standard icon definitions.
    """

    def __init__(self):
        """
        Initialize the notification manager and verify `notify-send` availability.

        Queries the system `PATH` to detect if the `notify-send` binary is present. If it
        is missing, a warning is logged and desktop notifications are marked as unavailable.
        """
        self._notify_send_available = check_command_exists("notify-send")

        if not self._notify_send_available:
            logger.warning(
                "notify-send not found. Desktop notifications will be disabled. "
                "Install libnotify to enable notifications."
            )

    def is_available(self) -> bool:
        """
        Check if desktop notifications are available on the system.

        Returns:
            bool: `True` if the `notify-send` CLI tool is available, `False` otherwise.

        Examples:
            >>> from archcare.core.notifications import NotificationManager
            >>> manager = NotificationManager()
            >>> isinstance(manager.is_available(), bool)
            True
        """
        return self._notify_send_available

    def send_notification(
        self,
        title: str,
        message: str,
        urgency: NotificationUrgency = NotificationUrgency.NORMAL,
        icon: NotificationIcon | str = NotificationIcon.INFO,
        timeout: int = 5000,
        app_name: str = "Archcare",
    ) -> bool:
        """
        Send a desktop notification using `notify-send`.

        Assembles and executes the low-level `notify-send` command with custom
        arguments. This operation includes a short execution timeout of 5 seconds
        to prevent blocks in headless environments where standard DBus message buses
        are unreachable or hanging.

        Args:
            title (str): Bold notification title header.
            message (str): Body text of the notification.
            urgency (NotificationUrgency): Urgency level of the alert. Defaults to `NORMAL`.
            icon (NotificationIcon | str): An icon enumeration value or a custom
                system theme icon name/file path. Defaults to `INFO`.
            timeout (int): Duration in milliseconds before the notification expires
                and fades out (0 means no timeout). Defaults to `5000` (5 seconds).
            app_name (str): Calling application identifier shown by modern desktop managers.
                Defaults to `"Archcare"`.

        Returns:
            bool: `True` if the command executed with exit code 0; `False` if notifications
                are unavailable, timed out, or returned an error status.

        Examples:
            >>> from archcare.core.notifications import NotificationManager, NotificationUrgency
            >>> manager = NotificationManager()
            >>> # Send a generic notification safely
            >>> result = manager.send_notification(
            ...     title="Test Notification",
            ...     message="Hello World!",
            ...     urgency=NotificationUrgency.LOW,
            ... )
            >>> isinstance(result, bool)
            True
        """
        if not self._notify_send_available:
            logger.warning(f"Skipping notification (notify-send not available): {title}")
            return False

        try:
            # Convert icon to string if it's an enum
            icon_str = str(icon) if isinstance(icon, NotificationIcon) else icon

            # Build notify-send command
            cmd = [
                "notify-send",
                "--app-name",
                app_name,
                "--urgency",
                str(urgency),
                "--icon",
                icon_str,
                "--expire-time",
                str(timeout),
                title,
                message,
            ]

            result = run_command(cmd, timeout=5)

            if not result.success:
                logger.error(
                    f"notify-send failed with exit code {result.returncode}: "
                    f"{result.stderr.strip()}"
                )
                return False

            logger.debug(f"Notification sent: {title}")
            return True

        except subprocess.TimeoutExpired:
            logger.error("notify-send timed out")
            return False
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")
            return False

    def send_maintenance_notification(
        self,
        severity: IssueSeverity,
        tasks_count: int,
        summary: str,
        timeout: int = 10000,
    ) -> bool:
        """
        Send a maintenance-specific notification based on issue severity.

        Maps the core's standard [IssueSeverity][] enum into low-level notification levels and
        appropriate alert header titles, helping the user instantly identify system state urgency.

        Args:
            severity (IssueSeverity): The classification rating of the found issues.
            tasks_count (int): The number of individual tasks currently requiring attention.
                Must be non-negative.
            summary (str): Short bulleted list or message describing the issue highlights.
            timeout (int): Notification screen display duration in milliseconds.
                Defaults to `10000` (10 seconds).

        Returns:
            bool: `True` if the notification was sent successfully, `False` otherwise.

        Examples:
            >>> from archcare.core.notifications import NotificationManager
            >>> from archcare.core.models import IssueSeverity
            >>> manager = NotificationManager()
            >>> result = manager.send_maintenance_notification(
            ...     severity=IssueSeverity.CRITICAL, tasks_count=1, summary="Mirror sync is broken!"
            ... )
            >>> isinstance(result, bool)
            True
        """
        # Map severity to urgency and icon
        severity_config: dict[str, dict[str, Any]] = {
            "critical": {
                "urgency": NotificationUrgency.CRITICAL,
                "icon": NotificationIcon.ERROR,
                "title": "🟥 Critical Maintenance Required",
            },
            "warning": {
                "urgency": NotificationUrgency.NORMAL,
                "icon": NotificationIcon.WARNING,
                "title": "🟨 Maintenance Tasks Due",
            },
            "info": {
                "urgency": NotificationUrgency.LOW,
                "icon": NotificationIcon.INFO,
                "title": "🟦 Maintenance Information",
            },
        }

        # Get severity config value from the value of maintenance_issue
        config = severity_config.get(severity.value, severity_config["info"])

        # Build title and message
        task_word = "task" if tasks_count == 1 else "tasks"
        message = f"{tasks_count} {task_word} need attention.\n{summary}"

        return self.send_notification(
            title=config["title"],
            message=message,
            urgency=config["urgency"],
            icon=config["icon"],
            timeout=timeout,
        )

    def send_task_result_notification(
        self,
        task_name: str,
        success: bool,
        message: str | None = None,
        timeout: int = 5000,
    ) -> bool:
        """
        Send a desktop notification representing a single task execution result.

        Formats standard success symbols and lower urgency settings for successful tasks,
        or alert indicators and higher urgency settings for failed executions.

        Args:
            task_name (str): Simple readable identifier of the completed task.
            success (bool): Whether the task completed successfully.
            message (str | None): Optional detailed message. If `None`, defaults to
                `"Task completed successfully"` or `"Task failed"`.
            timeout (int): Notification display timeout in milliseconds.
                Defaults to `5000` (5 seconds).

        Returns:
            bool: `True` if the notification was sent successfully, `False` otherwise.

        Examples:
            >>> from archcare.core.notifications import NotificationManager
            >>> manager = NotificationManager()
            >>> # Succeeded run
            >>> manager.send_task_result_notification(
            ...     task_name="failed-services", success=True
            ... ) in (True, False)
            True

            >>> # Failed run with custom message
            >>> manager.send_task_result_notification(
            ...     task_name="health-check", success=False, message="High CPU usage detected!"
            ... ) in (True, False)
            True
        """
        if success:
            title = f"✓ {task_name} completed"
            urgency = NotificationUrgency.LOW
            icon = NotificationIcon.SUCCESS
        else:
            title = f"✗ {task_name} failed"
            urgency = NotificationUrgency.NORMAL
            icon = NotificationIcon.ERROR

        body = message or ("Task completed successfully" if success else "Task failed")

        return self.send_notification(
            title=title,
            message=body,
            urgency=urgency,
            icon=icon,
            timeout=timeout,
        )
