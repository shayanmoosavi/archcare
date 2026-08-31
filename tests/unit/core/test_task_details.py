"""Unit tests for per-task detail dataclasses."""

import dataclasses

import pytest

from archcare.core import (
    FailedServiceInfo,
    FailedServicesDetails,
    HealthCheckDetails,
    HealthCheckSummary,
    IssueSeverity,
    MaintenanceCheckDetails,
    MaintenanceCheckSummary,
    MaintenanceIssue,
    MirrorlistUpdateDetails,
)
from archcare.utils.info_models import MirrorlistInfo

# ---------------------------------------------------------------------------
# FailedServiceInfo
# ---------------------------------------------------------------------------


class TestFailedServiceInfo:
    def test_defaults(self):
        info = FailedServiceInfo(service="sshd.service")

        assert info.description == ""
        assert info.active == "unknown"
        assert info.main_pid is None
        assert info.logs == []

    def test_custom_values(self):
        info = FailedServiceInfo(
            service="sshd.service",
            description="SSH daemon",
            active="failed",
            main_pid=1234,
            logs=["line 1", "line 2"],
        )

        assert info.description == "SSH daemon"
        assert info.active == "failed"
        assert info.main_pid == 1234
        assert info.logs == ["line 1", "line 2"]

    def test_is_frozen(self):
        info = FailedServiceInfo(service="sshd.service")

        with pytest.raises(dataclasses.FrozenInstanceError):
            info.service = "other.service"  # ty:ignore[invalid-assignment]

    def test_default_logs_list_not_shared_across_instances(self):
        first = FailedServiceInfo(service="a")
        second = FailedServiceInfo(service="b")

        assert first.logs is not second.logs


# ---------------------------------------------------------------------------
# FailedServicesDetails
# ---------------------------------------------------------------------------


class TestFailedServicesDetails:
    def test_defaults(self):
        details = FailedServicesDetails()

        assert details.total_failed == 0
        assert details.actual_failures == 0
        assert details.ignored == 0
        assert details.ignored_services == []
        assert details.failed_services == []

    def test_custom_values(self):
        info = FailedServiceInfo(service="sshd.service")
        details = FailedServicesDetails(
            total_failed=5,
            actual_failures=2,
            ignored=3,
            ignored_services=["known-flaky.service"],
            failed_services=[info],
        )

        assert details.total_failed == 5
        assert details.actual_failures == 2
        assert details.ignored == 3
        assert details.ignored_services == ["known-flaky.service"]
        assert details.failed_services == [info]

    def test_is_frozen(self):
        details = FailedServicesDetails()

        with pytest.raises(dataclasses.FrozenInstanceError):
            details.total_failed = 99  # ty:ignore[invalid-assignment]

    def test_default_lists_not_shared_across_instances(self):
        first = FailedServicesDetails()
        second = FailedServicesDetails()

        assert first.ignored_services is not second.ignored_services
        assert first.failed_services is not second.failed_services


# ---------------------------------------------------------------------------
# MaintenanceCheckSummary
# ---------------------------------------------------------------------------


class TestMaintenanceCheckSummary:
    def test_defaults(self):
        summary = MaintenanceCheckSummary()

        assert summary.total_tasks_monitored == 0
        assert summary.critical_count == 0
        assert summary.warning_count == 0
        assert summary.info_count == 0

    def test_custom_values(self):
        summary = MaintenanceCheckSummary(
            total_tasks_monitored=10,
            critical_count=2,
            warning_count=3,
            info_count=5,
        )

        assert summary.total_tasks_monitored == 10
        assert summary.critical_count == 2
        assert summary.warning_count == 3
        assert summary.info_count == 5

    def test_is_frozen(self):
        summary = MaintenanceCheckSummary()

        with pytest.raises(dataclasses.FrozenInstanceError):
            summary.total_tasks_monitored = 10  # ty:ignore[invalid-assignment]

    def test_total_issues(self):
        summary = MaintenanceCheckSummary(
            total_tasks_monitored=10,
            critical_count=0,
            warning_count=3,
            info_count=2,
        )

        assert (
            summary.total_issues
            == summary.critical_count + summary.warning_count + summary.info_count
        )

    def test_has_issues(self):
        summary = MaintenanceCheckSummary(
            total_tasks_monitored=10,
            critical_count=0,
            warning_count=3,
            info_count=2,
        )

        assert summary.has_issues

        summary = MaintenanceCheckSummary(
            total_tasks_monitored=10,
            critical_count=0,
            warning_count=0,
            info_count=0,
        )

        assert not summary.has_issues


class TestSummaryMessage:
    def test_all_clear_when_no_issues(self):
        summary = MaintenanceCheckSummary(
            total_tasks_monitored=10,
            critical_count=0,
            warning_count=0,
            info_count=0,
        )
        assert summary.summary_message == "All maintenance tasks are up to date!"

    def test_single_severity_type(self):
        summary = MaintenanceCheckSummary(
            total_tasks_monitored=10,
            warning_count=1,
        )
        assert summary.summary_message == "Found 1 warning issue(s) requiring attention"

    def test_multiple_severity_types_are_comma_joined(self):
        summary = MaintenanceCheckSummary(
            total_tasks_monitored=10,
            critical_count=2,
            warning_count=1,
        )
        assert summary.summary_message == "Found 2 critical, 1 warning issue(s) requiring attention"

    def test_zero_count_categories_are_omitted(self):
        """
        critical+info present, warning absent - the message must not
        mention '0 warning' at all, only categories that actually have
        issues. Easy to break with an off-by-one in the join logic.
        """
        summary = MaintenanceCheckSummary(
            total_tasks_monitored=10,
            critical_count=1,
            info_count=1,
        )
        assert summary.summary_message == "Found 1 critical, 1 info issue(s) requiring attention"
        assert "warning" not in summary.summary_message


# ---------------------------------------------------------------------------
# MaintenanceCheckDetails
# ---------------------------------------------------------------------------


class TestMaintenanceCheckDetails:
    @staticmethod
    def _issue(name: str, severity: IssueSeverity) -> MaintenanceIssue:
        return MaintenanceIssue(
            task_name=name, severity=severity, description="d", recommendation="r"
        )

    def test_defaults(self):
        details = MaintenanceCheckDetails()
        assert details.critical_issues == []
        assert details.warning_issues == []
        assert details.info_issues == []
        assert details.summary == MaintenanceCheckSummary()

    def test_custom_values(self):
        details = MaintenanceCheckDetails(
            critical_issues=[self._issue("a", IssueSeverity.CRITICAL)],
            warning_issues=[self._issue("b", IssueSeverity.WARNING)],
            info_issues=[self._issue("c", IssueSeverity.INFO)],
            summary=MaintenanceCheckSummary(critical_count=1, warning_count=1, info_count=1),
        )
        assert details.critical_issues == [self._issue("a", IssueSeverity.CRITICAL)]
        assert details.warning_issues == [self._issue("b", IssueSeverity.WARNING)]
        assert details.info_issues == [self._issue("c", IssueSeverity.INFO)]
        assert details.summary == MaintenanceCheckSummary(
            critical_count=1, warning_count=1, info_count=1
        )

    def test_default_lists_are_not_shared_across_instances(self):
        first = MaintenanceCheckDetails()
        second = MaintenanceCheckDetails()

        assert first.critical_issues is not second.critical_issues
        assert first.warning_issues is not second.warning_issues
        assert first.info_issues is not second.info_issues

    def test_summary_is_not_shared_across_instances(self):
        first = MaintenanceCheckDetails()
        second = MaintenanceCheckDetails()
        assert first.summary is not second.summary

    def test_excludes_info_issues(self):
        critical, warning, info = (
            self._issue("a", IssueSeverity.CRITICAL),
            self._issue("b", IssueSeverity.WARNING),
            self._issue("c", IssueSeverity.INFO),
        )
        details = MaintenanceCheckDetails(
            critical_issues=[critical], warning_issues=[warning], info_issues=[info]
        )
        tasks_needing_attention = details.tasks_needing_attention
        assert tasks_needing_attention == [critical, warning]
        assert info not in details.tasks_needing_attention


# ---------------------------------------------------------------------------
# HealthCheckSummary
# ---------------------------------------------------------------------------


class TestHealthCheckSummary:
    def test_defaults(self):
        """
        Load-bearing beyond just data - HealthCheckFormatter reads these
        exact defaults directly (e.g. uptime == "unknown", pacman_healthy
        == False renders as "Issues Detected"), so pinning them here
        protects against a future change silently altering formatter
        output for a task that never actually got the chance to populate
        a field.
        """
        summary = HealthCheckSummary()

        assert summary.disk_usage_percent == 0.0
        assert summary.memory_usage_percent == 0.0
        assert summary.cpu_usage_percent == 0.0
        assert summary.filesystem_errors_count == 0
        assert summary.pacman_healthy is True
        assert summary.packages_healthy is True
        assert summary.uptime == "unknown"

    def test_custom_values(self):
        summary = HealthCheckSummary(
            disk_usage_percent=45.5,
            memory_usage_percent=60.0,
            cpu_usage_percent=12.3,
            filesystem_errors_count=1,
            pacman_healthy=False,
            packages_healthy=True,
            uptime="3 days",
        )

        assert summary.disk_usage_percent == 45.5
        assert summary.pacman_healthy is False
        assert summary.uptime == "3 days"

    def test_is_frozen(self):
        summary = HealthCheckSummary()

        with pytest.raises(dataclasses.FrozenInstanceError):
            summary.uptime = "1 day"  # ty:ignore[invalid-assignment]


# ---------------------------------------------------------------------------
# HealthCheckDetails
# ---------------------------------------------------------------------------


class TestHealthCheckDetails:
    def test_defaults(self):
        details = HealthCheckDetails()

        assert details.issues == []
        assert details.warnings == []
        assert details.total_checks == 0
        assert details.summary == HealthCheckSummary()

    def test_custom_values(self):
        summary = HealthCheckSummary(uptime="2 days")
        details = HealthCheckDetails(
            issues=["disk failing"],
            warnings=["high cpu"],
            total_checks=7,
            summary=summary,
        )

        assert details.issues == ["disk failing"]
        assert details.warnings == ["high cpu"]
        assert details.total_checks == 7
        assert details.summary is summary

    def test_is_frozen(self):
        details = HealthCheckDetails()

        with pytest.raises(dataclasses.FrozenInstanceError):
            details.total_checks = 99  # ty:ignore[invalid-assignment]

    def test_default_lists_and_summary_not_shared_across_instances(self):
        first = HealthCheckDetails()
        second = HealthCheckDetails()

        assert first.issues is not second.issues
        assert first.warnings is not second.warnings
        assert first.summary is not second.summary


# ---------------------------------------------------------------------------
# MirrorlistUpdateDetails
# ---------------------------------------------------------------------------


class TestMirrorlistUpdateDetails:
    def test_defaults(self):
        details = MirrorlistUpdateDetails()

        assert details.old_mirrors is None
        assert details.new_mirrors is None
        assert details.old_info == MirrorlistInfo()
        assert details.new_info == MirrorlistInfo()
        assert details.backup_path is None

    def test_custom_values(self):
        details = MirrorlistUpdateDetails(
            old_mirrors=5,
            new_mirrors=8,
            old_info=MirrorlistInfo(total_mirrors=5, last_modified="2026-01-01"),
            new_info=MirrorlistInfo(total_mirrors=8),
            backup_path="/etc/pacman.d/mirrorlist_20260101.backup",
        )

        assert details.old_mirrors == 5
        assert details.new_mirrors == 8
        assert details.old_info.last_modified == "2026-01-01"
        assert details.backup_path == "/etc/pacman.d/mirrorlist_20260101.backup"

    def test_is_frozen(self):
        details = MirrorlistUpdateDetails()

        with pytest.raises(dataclasses.FrozenInstanceError):
            details.backup_path = "/somewhere"  # ty:ignore[invalid-assignment]

    def test_mirrorlist_info_is_not_shared_across_instances(self):
        first = MirrorlistUpdateDetails()
        second = MirrorlistUpdateDetails()

        assert first.old_info is not second.old_info
        assert first.new_info is not second.new_info
