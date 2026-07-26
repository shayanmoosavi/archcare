"""Unit tests for core data models."""

from dataclasses import dataclass

import pytest

from archcare.config import SkipReason, TaskStatus
from archcare.core import (
    IssueSeverity,
    MaintenanceIssue,
    TaskResult,
    failed,
    partial,
    skipped,
    success,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _issue(name: str, severity: IssueSeverity) -> MaintenanceIssue:
    return MaintenanceIssue(
        task_name=name, severity=severity, description="d", recommendation="r"
    )


@dataclass(frozen=True)
class MockTaskDetails:
    field_1: int = 0
    field_2: str = "SENTINEL"


# ---------------------------------------------------------------------------
# TaskResult - status checks
# ---------------------------------------------------------------------------


class TestTaskResultStatusChecks:
    @pytest.mark.parametrize(
        "status,method_name",
        [
            (TaskStatus.SUCCESS, "is_success"),
            (TaskStatus.FAILURE, "is_failed"),
            (TaskStatus.SKIPPED, "is_skipped"),
            (TaskStatus.PARTIAL, "is_partial"),
        ],
    )
    def test_matching_status_returns_true(self, status, method_name):
        result = TaskResult(status=status, message="x")
        assert getattr(result, method_name)() is True

    @pytest.mark.parametrize(
        "status,method_name",
        [
            (TaskStatus.SUCCESS, "is_failed"),
            (TaskStatus.FAILURE, "is_success"),
            (TaskStatus.SKIPPED, "is_partial"),
            (TaskStatus.PARTIAL, "is_skipped"),
        ],
    )
    def test_non_matching_status_returns_false(self, status, method_name):
        result = TaskResult(status=status, message="x")
        assert getattr(result, method_name)() is False


# ---------------------------------------------------------------------------
# TaskResult.__str__
# ---------------------------------------------------------------------------


class TestTaskResultStr:
    def test_basic_format(self):
        result = TaskResult(status=TaskStatus.SUCCESS, message="Cleanup completed")
        assert str(result) == "[SUCCESS] Cleanup completed"

    def test_zero_duration_is_omitted(self):
        result = TaskResult(status=TaskStatus.SUCCESS, message="x", duration_seconds=0.0)
        assert str(result) == "[SUCCESS] x"

    def test_positive_duration_is_included_and_formatted(self):
        result = TaskResult(status=TaskStatus.SUCCESS, message="x", duration_seconds=5.234)
        assert str(result) == "[SUCCESS] x (5.23s)"

    def test_error_is_appended_when_present(self):
        result = TaskResult(
            status=TaskStatus.FAILURE,
            message="Installation failed",
            error=str(RuntimeError("Disk full")),
            duration_seconds=2.1,
        )
        assert str(result) == "[FAILURE] Installation failed (2.10s) Error: Disk full"

    def test_error_omitted_when_none(self):
        result = TaskResult(status=TaskStatus.FAILURE, message="x")
        assert "Error:" not in str(result)


# ---------------------------------------------------------------------------
# IssueSeverity.__str__
# ---------------------------------------------------------------------------


class TestIssueSeverityStr:
    @pytest.mark.parametrize(
        "severity,expected",
        [
            (IssueSeverity.CRITICAL, "critical"),
            (IssueSeverity.WARNING, "warning"),
            (IssueSeverity.INFO, "info"),
        ],
    )
    def test_str_returns_lowercase_value(self, severity, expected):
        """
        Load-bearing beyond just display: maintenance_check.py's
        notification threshold logic does severity_map.get(str(severity)),
        so this exact mapping is worth confirming at the source rather
        than only trusting it worked in that file's own tests.
        """
        assert str(severity) == expected


# ---------------------------------------------------------------------------
# MaintenanceIssue.is_overdue
# ---------------------------------------------------------------------------


class TestMaintenanceIssueIsOverdue:
    @staticmethod
    def _issue(days_overdue: int | None) -> MaintenanceIssue:
        return MaintenanceIssue(
            task_name="x",
            severity=IssueSeverity.INFO,
            description="d",
            days_overdue=days_overdue,
            recommendation="r",
        )

    def test_positive_is_overdue(self):
        assert self._issue(5).is_overdue is True

    def test_none_is_not_overdue(self):
        assert self._issue(None).is_overdue is False

    def test_zero_is_not_overdue(self):
        assert self._issue(0).is_overdue is False

    def test_negative_is_not_overdue(self):
        assert self._issue(-3).is_overdue is False


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


class TestSuccessFactory:
    def test_sets_values_correctly(self):
        result = success("Update completed")
        assert result.status == TaskStatus.SUCCESS
        assert result.message == "Update completed"

    def test_sets_details_correctly(self):
        mock_details = MockTaskDetails(field_1=45, field_2="x")
        result = success("Update completed", details=mock_details)
        assert result.details is not None
        assert result.details.field_1 == 45
        assert result.details.field_2 == "x"


class TestFailedFactory:
    def test_sets_values_correctly(self):
        exc = ValueError("bad")
        mock_details = MockTaskDetails(field_2="Critical filesystem error")
        result = failed("Operation failed", error=str(exc), details=mock_details)
        assert result.status == TaskStatus.FAILURE
        assert result.error == "bad"
        assert result.details is not None
        assert result.details.field_2 == "Critical filesystem error"

    def test_error_defaults_to_none(self):
        result = failed("Operation failed")
        assert result.error is None


class TestSkippedFactory:
    def test_sets_values_correctly(self):
        result = skipped("Task disabled", skip_reason=SkipReason.DISABLED)
        assert result.status == TaskStatus.SKIPPED
        assert result.skip_reason == SkipReason.DISABLED
        assert result.message == "Task disabled"

    def test_skip_reason_can_be_none(self):
        result = skipped("Skipped for no particular reason", skip_reason=None)
        assert result.skip_reason is None

    def test_details_collected_from_kwargs(self):
        mock_details = MockTaskDetails(field_2="Due in 3 days")
        result = skipped("x", skip_reason=SkipReason.NOT_DUE, details=mock_details)
        assert result.details is not None
        assert result.details.field_2 == "Due in 3 days"


class TestPartialFactory:
    def test_sets_values_correctly(self):
        result = partial("3 of 5 checks passed")
        assert result.status == TaskStatus.PARTIAL
        assert result.message == "3 of 5 checks passed"

    def test_sets_details_correctly(self):
        mock_details = MockTaskDetails(field_1=3, field_2="2 checks failed")
        result = partial("x", details=mock_details)
        assert result.details is not None
        assert result.details.field_1 == 3
        assert result.details.field_2 == "2 checks failed"
