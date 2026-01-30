"""
Failed services task implementation for archcare.
"""

from loguru import logger

from archcare.config import ConfigLoader
from archcare.core.models import TaskResult, success, partial
from archcare.tasks import BaseTask
from archcare.utils import (
    check_command_exists,
    get_service_logs,
    get_service_status,
    get_systemd_failed_services,
)


class FailedServicesTask(BaseTask):
    """
    Check for failed systemd services.

    This task:
    - Lists all services in failed state
    - Filters out ignored services (from config)
    - Provides detailed status for each failed service
    - Shows recent logs to help diagnose issues
    """

    def pre_check(self) -> tuple[bool, str]:
        """
        Verify systemctl is available.

        Returns:
            (can_run, reason) tuple
        """
        if not check_command_exists("systemctl"):
            return False, "systemctl command not found (systemd not available)"

        return True, ""

    def should_run(self) -> tuple[bool, str]:
        """
        Check if there are any failed services to report.

        Returns:
            (should_run, reason) tuple
        """
        # Get all failed services
        failed_services = get_systemd_failed_services()

        # Load ignored services config
        config_loader = ConfigLoader(config_dir=self.settings.config_dir)
        ignored_config = config_loader.load_ignored_services()

        # Filter out ignored services
        actual_failures = [
            svc for svc in failed_services if not ignored_config.is_ignored(svc)
        ]

        if not actual_failures:
            return False, "No failed services found"

        return True, f"Found {len(actual_failures)} failed service(s)"

    def execute(self) -> TaskResult:
        """
        Check for failed services and provide detailed information.

        Returns:
            TaskResult with:
            - List of failed services
            - Status and description for each
            - Recent logs for diagnostics
        """
        logger.info("Checking for failed systemd services")

        # Get all failed services
        failed_services = get_systemd_failed_services()
        logger.debug(f"Found {len(failed_services)} failed services total")

        # Load ignored services config
        config_loader = ConfigLoader(config_dir=self.settings.config_dir)
        ignored_config = config_loader.load_ignored_services()

        # Filter out ignored services
        actual_failures = [
            svc for svc in failed_services if not ignored_config.is_ignored(svc)
        ]

        ignored_failures = [
            svc for svc in failed_services if ignored_config.is_ignored(svc)
        ]

        if ignored_failures:
            logger.info(
                f"Ignored {len(ignored_failures)} known failures: "
                f"{', '.join(ignored_failures)}"
            )

        # If no actual failures after filtering, this is a success
        # (shouldn't happen due to should_run(), but being defensive)
        if not actual_failures:
            return success(
                "No failed services found",
                total_failed=len(failed_services),
                ignored=len(ignored_failures),
            )

        # Gather detailed information about each failure
        failure_details = []

        for service_name in actual_failures:
            logger.debug(f"Getting details for {service_name}")

            # Get service status
            status = get_service_status(service_name)

            # Get recent logs (last 20 lines)
            logs = get_service_logs(service_name, lines=20)

            failure_details.append(
                {
                    "service": service_name,
                    "description": status.get("description", ""),
                    "active": status.get("active", "unknown"),
                    "main_pid": status.get("main_pid"),
                    "logs": logs[-10:] if logs else [],  # Last 10 lines
                }
            )

        message = f"Found {len(actual_failures)} failed service(s) requiring attention"

        return partial(
            message=message,
            failed_services=failure_details,
            total_failed=len(failed_services),
            actual_failures=len(actual_failures),
            ignored=len(ignored_failures),
            ignored_services=ignored_failures,
        )
