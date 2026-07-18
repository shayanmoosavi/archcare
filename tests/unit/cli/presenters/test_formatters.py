"""Unit tests for task detail formatters."""

from typing import Any
from unittest.mock import Mock

import pytest

from archcare.cli.presenters.formatters import (
    DefaultFormatter,
    FailedServicesFormatter,
    FormatterFactory,
    HealthCheckFormatter,
    MaintenanceCheckFormatter,
)
from archcare.core import MaintenanceIssue


def _joined(lines: list[str]) -> str:
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# DefaultFormatter
# ---------------------------------------------------------------------------


class TestDefaultFormatter:
    def test_formats_each_key_value_pair(self):
        output = _joined(DefaultFormatter().format({"foo": "bar", "count": 3}))

        assert "foo: bar" in output
        assert "count: 3" in output

    def test_skips_keys_starting_with_underscore(self):
        output = _joined(
            DefaultFormatter().format({"_internal": "hidden", "visible": "shown"})
        )

        assert "hidden" not in output
        assert "shown" in output


# ---------------------------------------------------------------------------
# FailedServicesFormatter
# ---------------------------------------------------------------------------


class TestFailedServicesFormatter:
    def test_includes_summary_counts(self):
        details = {"total_failed": 5, "actual_failures": 2, "ignored": 3}

        output = _joined(FailedServicesFormatter().format(details))

        assert "Total failed: 5" in output
        assert "Requiring attention: 2" in output
        assert "Ignored: 3" in output

    def test_lists_each_failed_service_with_description_and_status(self):
        details = {
            "failed_services": [
                {
                    "service": "sshd.service",
                    "description": "SSH daemon",
                    "active": "failed",
                }
            ]
        }

        output = _joined(FailedServicesFormatter().format(details))

        assert "sshd.service" in output
        assert "SSH daemon" in output
        assert "Status: failed" in output

    def test_omits_description_line_when_absent(self):
        details = {"failed_services": [{"service": "foo.service", "active": "failed"}]}

        lines = FailedServicesFormatter().format(details)

        # Only the "•" name line and the "Status:" line should exist for this
        # entry - no blank/empty description line in between.
        service_index = next(i for i, line in enumerate(lines) if "foo.service" in line)
        assert "Status:" in lines[service_index + 1]

    def test_includes_last_three_log_lines_only(self):
        logs = [f"log line {i}" for i in range(5)]
        details = {
            "failed_services": [
                {"service": "foo.service", "active": "failed", "logs": logs}
            ]
        }

        output = _joined(FailedServicesFormatter().format(details))

        assert "log line 2" in output
        assert "log line 3" in output
        assert "log line 4" in output
        assert "log line 0" not in output
        assert "log line 1" not in output

    def test_truncates_long_log_lines(self):
        long_log = "x" * 200
        details = {
            "failed_services": [
                {"service": "foo.service", "active": "failed", "logs": [long_log]}
            ]
        }

        output = _joined(FailedServicesFormatter().format(details))

        # Log lines with more than 160 characters are truncated to 160 and end with "…"
        assert "x" * 160 in output
        assert "x" * 161 not in output
