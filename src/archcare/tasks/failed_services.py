"""
Failed services task implementation for Archcare.

This module provides `FailedServicesTask`, a maintenance task that detects failed systemd units
and collects diagnostic information for each one. It is registered in the static task registry and
exposed to users as the `failed-services` command.

Workflow:
    1. `pre_check()` verifies that `systemctl` is available (i.e., the system runs systemd).
    2. `should_run()` lists failed units via [`get_systemd_failed_services`][], filters out services
        listed in `ignored-services.toml`, and skips the task if nothing actionable
        remains (`SkipReason.NO_WORK_NEEDED`).
    3. `execute()` gathers per-service diagnostics from `systemctl show` and recent journal logs via
        [`get_service_logs`][], and aggregates them into a [`FailedServicesDetails`][] payload.

Status semantics:
    - No failed units (or all failed units ignored): the task returns a
      `SUCCESS` result.
    - Any non-ignored failed unit: the task returns a `PARTIAL` result whose
      message lists the offending services, signaling that attention is needed.

!!! note "Ignored services"
    Ignored services are still tracked in the details payload
    (`ignored` and `ignored_services` fields) for auditing purposes, but they
    never affect the task outcome.

See Also:
    - [`BaseTask`][]: Abstract workflow this task implements
    - [`TaskResult`][]: The structured result object that the task returns
    - [`FailedServicesDetails`][]: Details schema produced by this task
    - [`TaskExecutor`][archcare.core.executor.TaskExecutor]: Coordinates task lifecycle
"""

from loguru import logger

from archcare.config import ConfigLoader, SkipReason
from archcare.core import (
    BaseTask,
    FailedServiceInfo,
    FailedServicesDetails,
    TaskResult,
    partial,
    success,
)
from archcare.utils import (
    check_command_exists,
    get_service_logs,
    get_service_status,
    get_systemd_failed_services,
)


class FailedServicesTask(BaseTask):
    """
    Check for failed systemd services and collect diagnostic details.

    This task scans the system for units in a failed state, filters out known/accepted failures
    configured in `ignored-services.toml`, and produces a report that can be rendered by the CLI
    presenter. For each non-ignored failure it gathers:

    - The unit's status (description, active state, main PID) via `systemctl show`
    - The last 10 journal log lines to help diagnose the issue

    This task follows the [`BaseTask`][] Template Method contract: `pre_check()` validates systemd
    availability, `should_run()` decides whether there is actual work, and `execute()` produces the
    [`FailedServicesDetails`][] payload.

    Example:
        ```toml title="ignored-services.toml"
        services = ['foo.service']
        ```

        Entries in this file are excluded from the failure count and therefore do not affect the
        task status.

    Attributes:
        settings (AppSettings): Application-wide settings (inherited); the
            `config_dir` property is used to locate `ignored-services.toml`.
    """

    def pre_check(self) -> tuple[bool, str]:
        """
        Verify that `systemctl` is available.

        This is a hard prerequisite: without systemd there is no way to query
        or manage services, so the task cannot run at all.

        Returns:
            (tuple[bool, str]): A tuple of:

                - `can_run` (`bool`): `True` if `systemctl` was found in `PATH`,
                    `False` otherwise.
                - `reason` (`str`): Explanation when the check fails (empty
                    string on success).
        """
        if not check_command_exists("systemctl"):
            return False, "systemctl command not found (systemd not available)"

        return True, ""

    def should_run(self) -> tuple[bool, str, SkipReason | None]:
        """
        Check whether there are any non-ignored failed services to report.

        Queries systemd for failed units, loads the ignored-services configuration from
        `self.settings.config_dir`, and filters out ignored entries. The task is skipped
        only if no actionable failures remain.

        Returns:
            (tuple[bool, str, SkipReason | None]): A tuple of:

                - `should_run` (`bool`): `True` if at least one non-ignored
                    failed service exists.
                - `reason` (`str`): Human-readable summary of the situation,
                    e.g. `"Found 2 failed service(s)"` or
                    `"No failed services found"`.
                - `skip_reason` ([`SkipReason`][archcare.config.SkipReason] | None):
                    `SkipReason.NO_WORK_NEEDED` when there is nothing to do,
                    `None` when the task should run.
        """
        # Get all failed services
        failed_services = get_systemd_failed_services()

        # Load ignored services config
        config_loader = ConfigLoader(config_dir=self.settings.config_dir)
        ignored_config = config_loader.load_ignored_services()

        # Filter out ignored services
        actual_failures = [svc for svc in failed_services if not ignored_config.is_ignored(svc)]

        if not actual_failures:
            return False, "No failed services found", SkipReason.NO_WORK_NEEDED

        return True, f"Found {len(actual_failures)} failed service(s)", None

    def execute(self) -> TaskResult[FailedServicesDetails]:
        """
        Check for failed services and provide detailed information.

        Scans for failed systemd units, excludes ignored services, then collects per-service
        diagnostics (description, active state, main PID, and the last 10 journal log lines)
        for each remaining failure.

        Returns:
            (TaskResult[FailedServicesDetails]):
                Result whose `details` is a `FailedServicesDetails`:

                - `success` when no non-ignored services are failed (the defensive branch —
                    `should_run()` normally prevents reaching `execute()` in this case).
                - `partial` when there are non-ignored failed services, with a message listing all
                    offending units and full diagnostic details in `details.failed_services`.

        Side Effects:
            - Emits log messages via Loguru at `info` and `debug` levels,
                including a summary of ignored known failures.
            - Invokes `systemctl show` and `journalctl` once per failed service.
        """
        logger.info("Checking for failed systemd services")

        # Get all failed services
        failed_services = get_systemd_failed_services()
        logger.debug(f"Found {len(failed_services)} failed services total")

        # Load ignored services config
        config_loader = ConfigLoader(config_dir=self.settings.config_dir)
        ignored_config = config_loader.load_ignored_services()

        # Filter out ignored services
        actual_failures = [svc for svc in failed_services if not ignored_config.is_ignored(svc)]

        ignored_failures = [svc for svc in failed_services if ignored_config.is_ignored(svc)]

        if ignored_failures:
            logger.info(
                f"Ignored {len(ignored_failures)} known failures: {', '.join(ignored_failures)}"
            )

        # If no actual failures after filtering, this is a success
        # (shouldn't happen due to should_run(), but being defensive)
        if not actual_failures:
            return success(
                "No failed services found",
                details=FailedServicesDetails(
                    total_failed=len(failed_services), ignored=len(ignored_failures)
                ),
            )

        # Gather detailed information about each failure
        failure_details: list[FailedServiceInfo] = []

        for service_name in actual_failures:
            logger.debug(f"Getting details for {service_name}")

            # Get service status
            status = get_service_status(service_name)

            # Get recent logs (last 20 lines)
            logs = get_service_logs(service_name, lines=20)

            failure_details.append(
                FailedServiceInfo(
                    service=service_name,
                    description=status.description,
                    active=status.active,
                    main_pid=status.main_pid,
                    logs=logs[-10:] if logs else [],
                )
            )

        message = (
            f"Found {len(actual_failures)} failed service(s) requiring attention:"
            f"\n    [bold red]• {'\n'.join(actual_failures)}[/bold red]"
        )

        return partial(
            message=message,
            details=FailedServicesDetails(
                failed_services=failure_details,
                total_failed=len(failed_services),
                actual_failures=len(actual_failures),
                ignored=len(ignored_failures),
                ignored_services=ignored_failures,
            ),
        )
