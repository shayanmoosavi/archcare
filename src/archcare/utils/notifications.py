"""
Desktop notification utilities for archcare.

Provides desktop notifications using notify-send with fallback handling.
"""

import subprocess
from enum import Enum
from typing import Any

from loguru import logger

from archcare.core.models import MaintenanceIssue
from .system import check_command_exists, run_command


class NotificationUrgency(Enum):
    """Urgency levels for notifications."""

    LOW = "low"
    NORMAL = "normal"
    CRITICAL = "critical"

    def __str__(self) -> str:
        return self.value


class NotificationIcon(Enum):
    """Standard icons for notifications."""

    INFO = "dialog-information"
    WARNING = "dialog-warning"
    ERROR = "dialog-error"
    SUCCESS = "emblem-default"
    MAINTENANCE = "system-software-update"

    def __str__(self) -> str:
        return self.value


class NotificationManager:
    """Manages desktop notifications using notify-send."""

    def __init__(self):
        """Initialize notification manager and check for notify-send availability."""
        self._notify_send_available = check_command_exists("notify-send")

        if not self._notify_send_available:
            logger.warning(
                "notify-send not found. Desktop notifications will be disabled. "
                "Install libnotify to enable notifications."
            )

    def is_available(self) -> bool:
        """
        Check if notifications are available.

        Returns:
            True if notify-send is available and notifications can be sent
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
        Send a desktop notification.

        Args:
            title: Notification title
            message: Notification message body
            urgency: Urgency level (low, normal, critical)
            icon: Icon name or path (can be NotificationIcon enum or custom string)
            timeout: Timeout in milliseconds (0 for no timeout)
            app_name: Application name to show in notification

        Returns:
            True if notification was sent successfully, False otherwise
        """
        if not self._notify_send_available:
            logger.warning(
                f"Skipping notification (notify-send not available): {title}"
            )
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
        maintenance_issue: MaintenanceIssue,
        tasks_count: int,
        summary: str,
        timeout: int = 10000,
    ) -> bool:
        """
        Send a maintenance-specific notification.

        Args:
            maintenance_issue: The MaintenanceIssue instance for the checked task
            tasks_count: Number of tasks needing attention
            summary: Brief summary of issues
            timeout: Timeout in milliseconds

        Returns:
            True if notification was sent successfully
        """
        # Map severity to urgency and icon
        severity_config: dict[str, dict[str, Any]] = {
            "critical": {
                "urgency": NotificationUrgency.CRITICAL,
                "icon": NotificationIcon.ERROR,
                "title": f"Critical Maintenance Required",
            },
            "warning": {
                "urgency": NotificationUrgency.NORMAL,
                "icon": NotificationIcon.WARNING,
                "title": "Maintenance Tasks Due",
            },
            "info": {
                "urgency": NotificationUrgency.LOW,
                "icon": NotificationIcon.INFO,
                "title": "Maintenance Information",
            },
        }

        # Get severity config value from the value of maintenance_issue
        config = severity_config.get(
            str(maintenance_issue.severity), severity_config["info"]
        )

        # Build title and message
        title = maintenance_issue.severity_emoji + config["title"]
        task_word = "task" if tasks_count == 1 else "tasks"
        message = f"{tasks_count} {task_word} need attention.\n{summary}"

        return self.send_notification(
            title=title,
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
        Send a notification for a task execution result.

        Args:
            task_name: Name of the task
            success: Whether the task succeeded
            message: Optional additional message
            timeout: Timeout in milliseconds

        Returns:
            True if notification was sent successfully
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


# Global notification manager instance
_notification_manager: NotificationManager | None = None


def get_notification_manager() -> NotificationManager:
    """
    Get the global notification manager instance.

    Returns:
        NotificationManager instance (singleton)
    """
    global _notification_manager
    if not _notification_manager:
        _notification_manager = NotificationManager()
    return _notification_manager


def send_notification(
    title: str,
    message: str,
    urgency: NotificationUrgency = NotificationUrgency.NORMAL,
    icon: NotificationIcon | str = NotificationIcon.INFO,
    timeout: int = 5000,
) -> bool:
    """
    Helper function to send a notification using the global manager.

    Args:
        title: Notification title
        message: Notification message body
        urgency: Urgency level
        icon: Icon name or NotificationIcon enum
        timeout: Timeout in milliseconds

    Returns:
        True if notification was sent successfully
    """
    manager = get_notification_manager()
    return manager.send_notification(title, message, urgency, icon, timeout)


def is_notification_available() -> bool:
    """
    Check if desktop notifications are available on this system.

    Returns:
        True if notifications can be sent, False otherwise
    """
    manager = get_notification_manager()
    return manager.is_available()
