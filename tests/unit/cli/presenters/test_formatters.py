"""Unit tests for task detail formatters."""

from unittest.mock import Mock

import pytest

from archcare.cli.presenters.formatters import (
    FailedServicesFormatter,
    HealthCheckFormatter,
    MaintenanceCheckFormatter,
)
from archcare.core import (
    FailedServiceInfo,
    FailedServicesDetails,
    HealthCheckDetails,
    HealthCheckSummary,
    MaintenanceCheckDetails,
    MaintenanceIssue,
)


def _joined(lines: list[str]) -> str:
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# FailedServicesFormatter
# ---------------------------------------------------------------------------


class TestFailedServicesFormatter:
    def test_includes_summary_counts(self):
        details = FailedServicesDetails(
            total_failed=5,
            actual_failures=2,
            ignored=3,
        )

        output = _joined(FailedServicesFormatter().format(details))

        assert "Total failed: 5" in output
        assert "Requiring attention: 2" in output
        assert "Ignored: 3" in output

    def test_lists_each_failed_service_with_description_and_status(self):
        details = FailedServicesDetails(
            failed_services=[
                FailedServiceInfo(
                    service="sshd.service",
                    description="SSH daemon",
                    active="failed",
                )
            ]
        )

        output = _joined(FailedServicesFormatter().format(details))

        assert "sshd.service" in output
        assert "SSH daemon" in output
        assert "Status: failed" in output

    def test_omits_description_line_when_absent(self):
        details = FailedServicesDetails(
            failed_services=[
                FailedServiceInfo(
                    service="foo.service",
                    active="failed",
                )
            ]
        )

        lines = FailedServicesFormatter().format(details)

        # Only the "•" name line and the "Status:" line should exist for this
        # entry - no blank/empty description line in between.
        service_index = next(i for i, line in enumerate(lines) if "foo.service" in line)
        assert "Status:" in lines[service_index + 1]

    def test_includes_last_three_log_lines_only(self):
        logs = [f"log line {i}" for i in range(5)]
        details = FailedServicesDetails(
            failed_services=[
                FailedServiceInfo(
                    service="foo.service",
                    active="failed",
                    logs=logs,
                )
            ]
        )

        output = _joined(FailedServicesFormatter().format(details))

        assert "log line 2" in output
        assert "log line 3" in output
        assert "log line 4" in output
        assert "log line 0" not in output
        assert "log line 1" not in output

    def test_truncates_long_log_lines(self):
        long_log = "x" * 200
        details = FailedServicesDetails(
            failed_services=[
                FailedServiceInfo(
                    service="foo.service",
                    active="failed",
                    logs=[long_log],
                )
            ]
        )

        output = _joined(FailedServicesFormatter().format(details))

        # Log lines with more than 160 characters are truncated to 160 and end with "…"
        assert "x" * 160 in output
        assert "x" * 161 not in output


# ---------------------------------------------------------------------------
# HealthCheckFormatter
# ---------------------------------------------------------------------------


class TestHealthCheckFormatter:
    def test_no_critical_issues_section_when_empty(self):
        output = _joined(HealthCheckFormatter().format(HealthCheckDetails(issues=[])))

        assert "Critical Issues:" not in output

    def test_lists_critical_issues(self):
        output = _joined(
            HealthCheckFormatter().format(HealthCheckDetails(issues=["disk failing"]))
        )

        assert "Critical Issues:" in output
        assert "disk failing" in output

    def test_lists_warnings(self):
        output = _joined(
            HealthCheckFormatter().format(HealthCheckDetails(warnings=["low memory"]))
        )

        assert "Warnings:" in output
        assert "low memory" in output

    @pytest.mark.parametrize(
        "key,pct,expected_color",
        [
            ("disk_usage_percent", 95.0, "red"),
            ("disk_usage_percent", 85.0, "yellow"),
            (
                "disk_usage_percent",
                90.0,
                "yellow",
            ),  # boundary: not > 90, falls to 80 tier
            ("disk_usage_percent", 50.0, "green"),
            ("memory_usage_percent", 95.0, "red"),
            ("memory_usage_percent", 50.0, "green"),
            ("cpu_usage_percent", 95.0, "yellow"),  # cpu has no red tier
            ("cpu_usage_percent", 90.0, "green"),  # boundary: not > 90
            ("cpu_usage_percent", 50.0, "green"),
        ],
    )
    def test_resource_usage_color_thresholds(self, key, pct, expected_color):
        summary = {key: pct}

        output = _joined(
            HealthCheckFormatter().format(
                HealthCheckDetails(summary=HealthCheckSummary(**summary))
            )
        )

        assert f"[{expected_color}]{pct:.1f}%[/{expected_color}]" in output

    def test_filesystem_errors_hidden_when_zero(self):
        output = _joined(
            HealthCheckFormatter().format(
                HealthCheckDetails(
                    summary=HealthCheckSummary(filesystem_errors_count=0)
                )
            )
        )

        assert "Filesystem Errors:" not in output

    def test_filesystem_errors_shown_when_present(self):
        output = _joined(
            HealthCheckFormatter().format(
                HealthCheckDetails(
                    summary=HealthCheckSummary(filesystem_errors_count=2)
                )
            )
        )

        assert "Filesystem Errors:" in output
        assert "2" in output

    @pytest.mark.parametrize(
        "key,healthy,expected_fragment",
        [
            ("pacman_healthy", True, "Healthy"),
            ("pacman_healthy", False, "Issues Detected"),
            ("packages_healthy", True, "Healthy"),
            ("packages_healthy", False, "Issues Detected"),
        ],
    )
    def test_pacman_and_package_health_status(self, key, healthy, expected_fragment):
        output = _joined(
            HealthCheckFormatter().format(
                HealthCheckDetails(summary=HealthCheckSummary(**{key: healthy}))
            )
        )

        assert expected_fragment in output

    def test_uptime_defaults_to_unknown_when_absent(self):
        output = _joined(
            HealthCheckFormatter().format(
                HealthCheckDetails(summary=HealthCheckSummary())
            )
        )

        assert "System Uptime: unknown" in output

    def test_uptime_shown_when_present(self):
        output = _joined(
            HealthCheckFormatter().format(
                HealthCheckDetails(summary=HealthCheckSummary(uptime="3 days"))
            )
        )

        assert "System Uptime: 3 days" in output


# ---------------------------------------------------------------------------
# MaintenanceCheckFormatter
# ---------------------------------------------------------------------------


class TestMaintenanceCheckFormatter:
    def test_includes_summary_counts(self):
        details = MaintenanceCheckDetails(
            total_tasks_monitored=4,
            critical_count=1,
            warning_count=2,
            info_count=0,
        )

        output = _joined(MaintenanceCheckFormatter().format(details))

        assert "Total tasks monitored: 4" in output
        assert "Critical issues: 1" in output
        assert "Warning issues: 2" in output
        assert "Informational issues: 0" in output

    def test_no_attention_section_when_list_empty(self):
        output = _joined(
            MaintenanceCheckFormatter().format(
                MaintenanceCheckDetails(tasks_needing_attention=[])
            )
        )

        assert "Tasks needing attention:" not in output

    @pytest.mark.parametrize(
        "severity,expected_fragment",
        [
            ("critical", "CRITICAL"),
            ("warning", "WARNING"),
            ("info", "INFO"),
        ],
    )
    def test_lists_tasks_needing_attention_with_severity(
        self, severity, expected_fragment
    ):
        issue = Mock(spec=MaintenanceIssue)
        issue.task_name = "update-mirrorlist"
        issue.severity = severity

        output = _joined(
            MaintenanceCheckFormatter().format(
                MaintenanceCheckDetails(tasks_needing_attention=[issue])
            )
        )

        assert "update-mirrorlist" in output
        assert expected_fragment in output
