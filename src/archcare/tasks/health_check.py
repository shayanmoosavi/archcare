"""
Health check task implementation for archcare.
"""

from typing import Any

from archcare.core.models import TaskResult, partial, success, failed
from archcare.tasks.base import BaseTask
from archcare.utils import (
    check_filesystem_errors,
    check_pacman_database,
    check_package_files,
    format_bytes,
    get_cpu_info,
    get_disk_usage,
    get_memory_info,
    get_system_uptime,
)


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

    def execute(self) -> TaskResult:
        """
        Run all health checks and collect results.

        Returns:
            TaskResult with health check details
        """
        self.logger.info("Starting system health checks")

        issues: list[str] = []
        warnings: list[str] = []
        checks: dict[str, Any] = {}

        total_checks = 0

        # Check disk space
        disk_percent = self._check_disk_space(checks, issues, warnings)
        total_checks += 1

        # Check memory usage
        mem_percent = self._check_memory_usage(checks, issues, warnings)
        total_checks += 1

        # Check CPU load
        cpu_percent = self._check_cpu_load(checks, warnings)
        total_checks += 1

        # Check for filesystem errors
        fs_errors = self._check_filesystem_errors(checks, issues)
        total_checks += 1

        # Check pacman database health
        pacman_ok = self._check_pacman_database_health(checks, issues)
        total_checks += 1

        # Check installed package files integrity
        packages_ok = self._check_installed_package_files(checks, issues)
        total_checks += 1

        # Check system uptime
        uptime = self._check_system_uptime(checks)
        total_checks += 1

        if issues:
            message = f"Health check found {len(issues)} critical issue(s)"
            self.logger.info(f"Health check complete: {message}")
            return failed(
                message=message,
                error=None,
                issues=issues,
                warnings=warnings,
                checks=checks,
                total_checks=total_checks,
                summary={
                    "disk_usage_percent": disk_percent,
                    "memory_usage_percent": mem_percent,
                    "cpu_usage_percent": cpu_percent,
                    "filesystem_errors_count": len(fs_errors),
                    "pacman_healthy": pacman_ok,
                    "packages_healthy": packages_ok,
                    "uptime": uptime,
                },
            )
        elif warnings:
            message = f"Health check found {len(warnings)} warning(s)"
            self.logger.info(f"Health check complete: {message}")
            return partial(
                message=message,
                warnings=warnings,
                checks=checks,
                total_checks=total_checks,
                summary={
                    "disk_usage_percent": disk_percent,
                    "memory_usage_percent": mem_percent,
                    "cpu_usage_percent": cpu_percent,
                    "filesystem_errors_count": len(fs_errors),
                    "pacman_healthy": pacman_ok,
                    "packages_healthy": packages_ok,
                    "uptime": uptime,
                },
            )
        else:
            message = "All health checks passed"
            self.logger.info(f"Health check complete: {message}")
            return success(
                message=message,
                checks=checks,
                total_checks=total_checks,
                summary={
                    "disk_usage_percent": disk_percent,
                    "memory_usage_percent": mem_percent,
                    "cpu_usage_percent": cpu_percent,
                    "filesystem_errors_count": len(fs_errors),
                    "pacman_healthy": pacman_ok,
                    "packages_healthy": packages_ok,
                    "uptime": uptime,
                },
            )

    def _check_system_uptime(self, checks: dict[str, Any]) -> str:
        self.logger.debug("Getting system uptime")
        uptime = get_system_uptime()
        checks["uptime"] = uptime
        self.logger.info(f"System uptime: {uptime}")

        return uptime

    def _check_installed_package_files(
        self, checks: dict[str, Any], issues: list[str]
    ) -> bool:
        self.logger.debug("Checking installed package files integrity")
        packages_ok, packages_msg = check_package_files()
        checks["package_files"] = {"healthy": packages_ok, "message": packages_msg}

        if not packages_ok:
            issues.append(f"Critical: {packages_msg}")
        else:
            self.logger.debug(packages_msg)

        return packages_ok

    def _check_pacman_database_health(
        self, checks: dict[str, Any], issues: list[str]
    ) -> bool:
        self.logger.debug("Checking pacman database")
        pacman_ok, pacman_msg = check_pacman_database()
        checks["pacman"] = {"healthy": pacman_ok, "message": pacman_msg}

        if not pacman_ok:
            issues.append(f"Critical: {pacman_msg}")
        else:
            self.logger.debug(pacman_msg)

        return pacman_ok

    def _check_filesystem_errors(
        self, checks: dict[str, Any], issues: list[str]
    ) -> list[str]:
        self.logger.debug("Checking for filesystem errors")
        fs_errors = check_filesystem_errors()
        checks["filesystem_errors"] = fs_errors

        if fs_errors:
            issues.append(f"Critical: {len(fs_errors)} filesystem error(s) detected")
            for error in fs_errors[:3]:  # Show first 3
                self.logger.warning(f"Filesystem error: {error}")

        return fs_errors

    def _check_cpu_load(self, checks: dict[str, Any], warnings: list[str]) -> float:
        self.logger.debug("Checking CPU load")
        cpu = get_cpu_info()
        checks["cpu"] = cpu

        cpu_percent = cpu["percent"]
        load_avg = cpu["load_avg"]
        cpu_count = cpu["count"] or 1

        if cpu_percent > 90:
            warnings.append(f"Warning: High CPU usage at {cpu_percent}%")

        if load_avg:
            # Load average should ideally be below number of CPU cores
            load_1min = load_avg[0]
            if load_1min > cpu_count * 2:
                warnings.append(
                    f"Warning: High load average {load_1min:.2f} (CPUs: {cpu_count})"
                )

        return cpu_percent

    def _check_memory_usage(
        self, checks: dict[str, Any], issues: list[str], warnings: list[str]
    ) -> float:
        self.logger.debug("Checking memory usage")
        memory = get_memory_info()
        checks["memory"] = memory

        mem_percent = memory["percent"]
        swap_percent = memory["swap_percent"]

        if mem_percent > 90:
            issues.append(
                f"Critical: Memory usage at {mem_percent}% ({format_bytes(memory['available'])} available)"
            )
        elif mem_percent > 80:
            warnings.append(
                f"Warning: Memory usage at {mem_percent}% ({format_bytes(memory['available'])} available)"
            )

        if swap_percent > 50:
            warnings.append(f"Warning: High swap usage at {swap_percent}%")

        return mem_percent

    def _check_disk_space(
        self, checks: dict[str, Any], issues: list[str], warnings: list[str]
    ) -> float:
        self.logger.debug("Checking disk space")
        disk = get_disk_usage("/")
        checks["disk"] = disk

        disk_percent = disk["percent"]
        if disk_percent > 90:
            issues.append(
                f"Critical: Disk usage at {disk_percent}% ({format_bytes(disk['free'])} free)"
            )
        elif disk_percent > 80:
            warnings.append(
                f"Warning: Disk usage at {disk_percent}% ({format_bytes(disk['free'])} free)"
            )
        else:
            self.logger.debug(
                f"Disk usage: {disk_percent}% ({format_bytes(disk['free'])} free)"
            )

        return disk_percent
