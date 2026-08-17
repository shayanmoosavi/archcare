"""
Health check task implementation for archcare.
"""

import dataclasses

from loguru import logger

from archcare.config import TaskStatus
from archcare.core import (
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

from .base import BaseTask


class HealthCheckTask(BaseTask):
    """
    Perform comprehensive system health checks.

    This task checks:
    - Disk space usage
    - Memory usage
    - CPU load
    - Filesystem errors
    - Pacman database health
    - Package file integrity
    - System uptime
    """

    _CHECK_COUNT = len(dataclasses.fields(HealthCheckSummary))

    def execute(self) -> TaskResult[HealthCheckDetails]:
        """
        Run all health checks and collect results.

        Returns:
            TaskResult with health check details
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
        logger.debug("Getting system uptime")
        uptime = get_system_uptime()
        logger.info(f"System uptime: {uptime}")

        return uptime

    @staticmethod
    def _check_installed_package_files(issues: list[str]) -> bool:
        logger.debug("Checking installed package files integrity")
        packages_ok, packages_msg = check_package_files()

        if not packages_ok:
            issues.append(packages_msg)
        else:
            logger.debug(packages_msg)

        return packages_ok

    @staticmethod
    def _check_pacman_database_health(issues: list[str]) -> bool:
        logger.debug("Checking pacman database")
        pacman_ok, pacman_msg = check_pacman_database()

        if not pacman_ok:
            issues.append(pacman_msg)
        else:
            logger.debug(pacman_msg)

        return pacman_ok

    @staticmethod
    def _check_filesystem_errors(issues: list[str]) -> list[str]:
        logger.debug("Checking for filesystem errors")
        fs_errors = check_filesystem_errors()

        if fs_errors:
            issues.append(f"{len(fs_errors)} filesystem error(s) detected")
            for error in fs_errors[:3]:  # Show first 3
                logger.warning(f"Filesystem error: {error}")

        return fs_errors

    @staticmethod
    def _check_cpu_load(warnings: list[str]) -> float:
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
