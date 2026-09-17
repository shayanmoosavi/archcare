"""
Health check task implementation for archcare.

This module provides `HealthCheckTask`, a maintenance task that runs a suite of system health checks
and aggregates the results into a single report. It is registered in the static task registry
and exposed to users as the `health-check` command.

Checks performed (in order):

1. Disk space usage (`/` filesystem via `psutil`)
2. Memory and swap usage
3. CPU load (instantaneous percentage and load average)
4. Filesystem errors (e.g., Btrfs/ext4 corruption reports)
5. Pacman database integrity
6. Installed package file integrity (missing/modified files)
7. System uptime (informational only)

Severity semantics:
    Findings are collected into two buckets that determine the task outcome:

    - **Issues** (critical): disk or memory usage above 90%, filesystem errors, corrupted pacman
        database, or package file integrity violations. Any issue makes the task return a
        `FAILURE` result.
    - **Warnings**: disk or memory usage between 80-90%, swap usage above 50%, CPU usage above 90%,
        or load average exceeding twice the core count. Warnings with no issues produce a
        `PARTIAL` result.

!!! note "Progress reporting"
    The task starts a progress bar with exactly `HealthCheckTask._CHECK_COUNT` steps (one per check)
    and advances it after each check completes. Rendering is briefly paused around the package file
    integrity check so an interactive sudo password prompt can be displayed cleanly.

See Also:
    - [`BaseTask`][]: Abstract workflow this task implements
    - [`TaskResult`][]: The structured result object that the task returns
    - [`HealthCheckDetails`][]: Details schema produced by this task
    - [`HealthCheckSummary`][]: Aggregated metrics snapshot within the details
"""

import dataclasses

from loguru import logger

from archcare.config import TaskStatus
from archcare.core import (
    BaseTask,
    HealthCheckDetails,
    HealthCheckSummary,
    TaskResult,
    TaskStep,
    failed,
    partial,
    success,
)
from archcare.utils import (
    check_filesystem_errors,
    check_package_files,
    check_pacman_database,
    format_bytes,
    get_cpu_info,
    get_disk_usage,
    get_memory_info,
    get_system_uptime,
)


class HealthCheckTask(BaseTask):
    """
    Perform comprehensive system health checks and report findings by severity.

    The task runs seven independent checks — disk space, memory/swap, CPU load, filesystem errors,
    pacman database health, package file integrity, and uptime — and aggregates both the raw metrics
    (into a [`HealthCheckSummary`][]) and the categorized findings (into a
    [`HealthCheckDetails`][]).

    Severity thresholds:

    | Check                  | Warning                          | Critical (issue)   |
    | ---------------------- | -------------------------------- | ------------------ |
    | Disk usage (`/`)       | > 80%                            | > 90%              |
    | Memory usage           | > 80%                            | > 90%              |
    | Swap usage             | > 50%                            | —                  |
    | CPU usage              | > 90%                            | —                  |
    | Load average (1 min)   | > 2× CPU core count              | —                  |
    | Filesystem errors      | —                                | any error          |
    | Pacman database        | —                                | unhealthy          |
    | Package files          | —                                | unhealthy          |
    | System uptime          | —                                | — (informational)  |

    This task follows the [`BaseTask`][] Template Method contract. Unlike some tasks, it does not
    override `pre_check()` or `should_run()`: all checks are read-only queries that are always safe
    to perform, so the task runs whenever scheduled or forced.

    Attributes:
        _CHECK_COUNT (int): *(class-level)* Number of individual checks performed, derived from the
            field count of [`HealthCheckSummary`][]. Used as the progress bar total and reported as
            `total_checks` in the result details.
    """

    _CHECK_COUNT = len(dataclasses.fields(HealthCheckSummary))

    def execute(self) -> TaskResult[HealthCheckDetails]:
        """
        Run all health checks and collect results.

        Executes each check in sequence, appending critical findings to the `issues` list and
        non-critical findings to the `warnings` list, while advancing the progress bar between
        checks. Finally, builds a [`HealthCheckSummary`][] snapshot and selects the outcome:

        - `FAILURE` when any critical issue was found
        - `PARTIAL` when only warnings were found
        - `SUCCESS` when everything is healthy

        Returns:
            (TaskResult[HealthCheckDetails]):
                Result whose `details` is a `HealthCheckDetails` containing the categorized
                `issues`/`warnings` lists, the number of checks performed (`total_checks`), and the
                metrics `summary`.

        Side Effects:
            - Emits Loguru log messages at `info`/`debug`/`warning` levels.
            - Drives the injected progress reporter (start, advance per check,
              brief pause around the package file integrity check for sudo).
            - Queries system metrics via `psutil` and invokes pacman/filesystem
              check utilities.
        """
        logger.info("Starting system health checks")

        issues: list[str] = []
        warnings: list[str] = []

        self.progress.start(total=self._CHECK_COUNT)

        disk_percent = self._check_disk_space(issues, warnings)
        self.report_progress(TaskStep(name="Disk space", status=TaskStatus.SUCCESS))

        mem_percent = self._check_memory_usage(issues, warnings)
        self.report_progress(TaskStep(name="Memory usage", status=TaskStatus.SUCCESS))

        cpu_percent = self._check_cpu_load(warnings)
        self.report_progress(TaskStep(name="CPU load", status=TaskStatus.SUCCESS))

        fs_errors = self._check_filesystem_errors(issues)
        self.report_progress(TaskStep(name="Filesystem errors", status=TaskStatus.SUCCESS))

        pacman_ok = self._check_pacman_database_health(issues)
        self.report_progress(TaskStep(name="Pacman database", status=TaskStatus.SUCCESS))

        # Pausing the progress rendering so sudo prompt can be displayed correctly
        with self.progress.pause():
            packages_ok = self._check_installed_package_files(issues)
        self.report_progress(TaskStep(name="Package file integrity", status=TaskStatus.SUCCESS))

        uptime = self._check_system_uptime()
        self.report_progress(TaskStep(name="System uptime", status=TaskStatus.SUCCESS))

        summary = HealthCheckSummary(
            disk_usage_percent=disk_percent,
            memory_usage_percent=mem_percent,
            cpu_usage_percent=cpu_percent,
            filesystem_errors_count=len(fs_errors),
            pacman_healthy=pacman_ok,
            packages_healthy=packages_ok,
            uptime=uptime,
        )

        if issues:
            message = f"Health check found {len(issues)} critical issue(s)"
            logger.info(f"Health check complete: {message}")
            return failed(
                message=message,
                error=None,
                details=HealthCheckDetails(
                    issues=issues,
                    warnings=warnings,
                    total_checks=self._CHECK_COUNT,
                    summary=summary,
                ),
            )
        elif warnings:
            message = f"Health check found {len(warnings)} warning(s)"
            logger.info(f"Health check complete: {message}")
            return partial(
                message=message,
                details=HealthCheckDetails(
                    warnings=warnings,
                    total_checks=self._CHECK_COUNT,
                    summary=summary,
                ),
            )
        else:
            message = "All health checks passed"
            logger.info(f"Health check complete: {message}")
            return success(
                message=message,
                details=HealthCheckDetails(
                    total_checks=self._CHECK_COUNT,
                    summary=summary,
                ),
            )

    @staticmethod
    def _check_system_uptime() -> str:
        """
        Query and log the system uptime.

        Returns:
            str: Human-readable uptime string (e.g., `"5 days, 3:42"`),
                or `"unknown"` if unavailable.

        Side Effects:
            Emits Loguru log messages at `debug` and `info` levels.
        """
        logger.debug("Getting system uptime")
        uptime = get_system_uptime()
        logger.info(f"System uptime: {uptime}")

        return uptime

    @staticmethod
    def _check_installed_package_files(issues: list[str]) -> bool:
        """
        Verify the integrity of installed package files.

        Checks for missing or modified files belonging to installed pacman packages. On failure,
        records the explanatory message as a critical issue.

        Args:
            issues (list[str]): Accumulator list for critical issues; the failure message is
                appended here when the check fails.

        Returns:
            bool: `True` if all package files are intact, `False` otherwise.

        Side Effects:
            Emits Loguru log messages at `debug` level on success.
        """
        logger.debug("Checking installed package files integrity")
        packages_ok, packages_msg = check_package_files()

        if not packages_ok:
            issues.append(packages_msg)
        else:
            logger.debug(packages_msg)

        return packages_ok

    @staticmethod
    def _check_pacman_database_health(issues: list[str]) -> bool:
        """
        Verify pacman database integrity.

        On failure, records the explanatory message as a critical issue.

        Args:
            issues (list[str]): Accumulator list for critical issues; the
                failure message is appended here when the check fails.

        Returns:
            bool: `True` if the pacman database is healthy, `False` otherwise.

        Side Effects:
            Emits Loguru log messages at `debug` level on success.
        """
        logger.debug("Checking pacman database")
        pacman_ok, pacman_msg = check_pacman_database()

        if not pacman_ok:
            issues.append(pacman_msg)
        else:
            logger.debug(pacman_msg)

        return pacman_ok

    @staticmethod
    def _check_filesystem_errors(issues: list[str]) -> list[str]:
        """
        Scan the filesystem for corruption errors.

        Detects filesystem errors (e.g., Btrfs scrub failures, ext4 corruption reports). Any
        detected error is recorded as a critical issue, and the first three errors are additionally
        logged as warnings.

        Args:
            issues (list[str]): Accumulator list for critical issues; a summary message is appended
            when errors are found.

        Returns:
            list[str]: The detected filesystem error messages (empty if none).

        Side Effects:
            Emits Loguru log messages at `debug` and (on errors) `warning` levels.
        """
        logger.debug("Checking for filesystem errors")
        fs_errors = check_filesystem_errors()

        if fs_errors:
            issues.append(f"{len(fs_errors)} filesystem error(s) detected")
            for error in fs_errors[:3]:  # Show first 3
                logger.warning(f"Filesystem error: {error}")

        return fs_errors

    @staticmethod
    def _check_cpu_load(warnings: list[str]) -> float:
        """
        Measure CPU usage and load average, flagging sustained overload.

        Records a warning when instantaneous CPU usage exceeds 90%, and another when the 1-minute
        load average exceeds twice the number of CPU cores.

        Args:
            warnings (list[str]): Accumulator list for non-critical warnings;
                threshold violations are appended here.

        Returns:
            float: Current CPU usage percentage (0.0 if unavailable).

        Side Effects:
            Emits Loguru log messages at `debug` level.
        """
        logger.debug("Checking CPU load")
        cpu = get_cpu_info()

        cpu_percent = cpu.percent
        load_avg = cpu.load_avg
        cpu_count = cpu.cores or 1

        if cpu_percent > 90:
            warnings.append(f"High CPU usage at {cpu_percent}%")

        if load_avg:
            # Load average should ideally be below number of CPU cores
            load_1min = load_avg[0]
            if load_1min > cpu_count * 2:
                warnings.append(f"High load average {load_1min:.2f} (CPUs: {cpu_count})")

        return cpu_percent

    @staticmethod
    def _check_memory_usage(issues: list[str], warnings: list[str]) -> float:
        """
        Measure memory and swap usage, flagging pressure by severity.

        Memory usage above 90% is recorded as a critical issue, above 80% as a warning; both include
        the amount of free memory. Swap usage above 50% is recorded as a warning.

        Args:
            issues (list[str]): Accumulator list for critical issues.
            warnings (list[str]): Accumulator list for non-critical warnings.

        Returns:
            float: Current memory usage percentage (0.0 if unavailable).

        Side Effects:
            Emits Loguru log messages at `debug` level.
        """
        logger.debug("Checking memory usage")
        memory = get_memory_info()

        mem_percent = memory.percent
        swap_percent = memory.swap_percent

        if mem_percent > 90:
            issues.append(
                f"Memory usage at {mem_percent}% ({format_bytes(memory.available)} available)"
            )
        elif mem_percent > 80:
            warnings.append(
                f"Memory usage at {mem_percent}% ({format_bytes(memory.available)} available)"
            )

        if swap_percent > 50:
            warnings.append(f"High swap usage at {swap_percent}%")

        return mem_percent

    @staticmethod
    def _check_disk_space(issues: list[str], warnings: list[str]) -> float:
        """
        Measure root filesystem usage, flagging low disk space by severity.

        Usage above 90% is recorded as a critical issue, above 80% as a warning; both include the
        amount of free space. Healthy usage is only logged at `debug` level.

        Args:
            issues (list[str]): Accumulator list for critical issues.
            warnings (list[str]): Accumulator list for non-critical warnings.

        Returns:
            float: Root filesystem usage percentage (0.0 if unavailable).

        Side Effects:
            Emits Loguru log messages at `debug` level.
        """
        logger.debug("Checking disk space")
        disk = get_disk_usage("/")

        disk_percent = disk.percent
        if disk_percent > 90:
            issues.append(f"Disk usage at {disk_percent}% ({format_bytes(disk.free)} free)")
        elif disk_percent > 80:
            warnings.append(f"Disk usage at {disk_percent}% ({format_bytes(disk.free)} free)")
        else:
            logger.debug(f"Disk usage: {disk_percent}% ({format_bytes(disk.free)} free)")

        return disk_percent
