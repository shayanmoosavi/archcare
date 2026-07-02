"""Unit tests for system utility parsing and formatting logic."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from archcare.utils.system import (
    CommandResult,
    _get_boot_time,
    _get_service_description,
    _parse_active_status,
    _parse_loaded_status,
    _parse_main_pid,
    format_bytes,
    get_system_uptime,
)

# ---------------------------------------------------------------------------
# systemctl status parsing
# ---------------------------------------------------------------------------


class TestSystemctlParsing:
    def test_parse_loaded_status(self):
        # Service is loaded properly
        assert (
            _parse_loaded_status(
                "   Loaded: loaded (/usr/lib/systemd/system/dbus-broker.service; disabled; preset: disabled)"
            )
            is True
        )
        # Service is missing
        assert (
            _parse_loaded_status("Unit nonexistent.service could not be found.")
            is False
        )

    def test_parse_active_status_running(self):
        state, is_running = _parse_active_status(
            "   Active: active (running) since Mon 2026-06-26"
        )
        assert state == "active"
        assert is_running is True

    def test_parse_active_status_exited(self):
        # e.g., oneshot services
        state, is_running = _parse_active_status(
            "   Active: active (exited) since Mon 2026-06-26"
        )
        assert state == "active"
        assert is_running is False

    def test_parse_active_status_inactive(self):
        state, is_running = _parse_active_status("   Active: inactive (dead)")
        assert state == "inactive"
        assert is_running is False

    def test_parse_active_status_failed(self):
        state, is_running = _parse_active_status(
            "   Active: failed (Result: exit-code)"
        )
        assert state == "failed"
        assert is_running is False

    def test_parse_active_status_unknown(self):
        state, is_running = _parse_active_status(
            "   Active: something entirely unexpected"
        )
        assert state == "unknown"
        assert is_running is False

    def test_parse_main_pid_valid(self):
        assert (
            _parse_main_pid(" Main PID: 1234 (code=exited, status=0/SUCCESS)") == 1234
        )

    def test_parse_main_pid_invalid_or_missing(self):
        assert _parse_main_pid(" Main PID: unknown") is None
        assert _parse_main_pid(" Main PID:") is None
        assert _parse_main_pid("Some other line entirely") is None

    @pytest.mark.parametrize(
        "svc_name,out,desc",
        [
            (
                "acpid.service",
                "acpid.service loaded active running ACPI event daemon",
                "ACPI event daemon",
            ),
            (
                "systemd-random-seed.service",
                "systemd-random-seed.service loaded active exited Load/Save OS Random Seed",
                "Load/Save OS Random Seed",
            ),
            (
                "service-with-no-desc.service",
                "service-with-no-desc.service loaded active exited ",
                "",
            ),
        ],
    )
    def test_get_service_description_correctly_parses_found_service(
        self, svc_name, out, desc
    ):
        with patch("archcare.utils.system.run_systemctl") as mock_run:
            mock_run.return_value = CommandResult(
                command="",
                returncode=0,
                stdout=out,
                stderr="",
                success=True,
            )
            assert _get_service_description(svc_name) == desc

    def test_get_service_description_correctly_parses_not_found_service(self):
        with patch("archcare.utils.system.run_systemctl") as mock_run:
            mock_run.return_value = CommandResult(
                command="",
                returncode=0,
                stdout="",
                stderr="",
                success=True,
            )
            assert _get_service_description("nonexistent.service") == ""

    def test_get_service_description_returns_empty_when_command_fails(self):
        with patch("archcare.utils.system.run_systemctl") as mock_run:
            mock_run.return_value = CommandResult(
                command="",
                returncode=1,
                stdout="some.service loaded active running Some description",
                stderr="unit not found",
                success=False,
            )
            assert _get_service_description("some.service") == ""


# ---------------------------------------------------------------------------
# Boot time
# ---------------------------------------------------------------------------


class TestGetBootTime:
    def test_falls_back_to_now_on_psutil_failure(self):
        """
        Every other test mocks _get_boot_time() itself, so its own
        try/except around psutil.boot_time() has no coverage elsewhere.
        """
        with patch("psutil.boot_time", side_effect=Exception("no /proc/stat")):
            before = datetime.now()
            result = _get_boot_time()
            after = datetime.now()

        assert before <= result <= after


# ---------------------------------------------------------------------------
# Formatting and Calculations
# ---------------------------------------------------------------------------


class TestFormatting:
    @pytest.mark.parametrize(
        "bytes_val,bytes_expected",
        [
            (500, "500.00 B"),
            (1024, "1.00 KB"),
            (1024**2 * 1.5, "1.50 MB"),
            (1024**3 * 2.75, "2.75 GB"),
            (1024**4 * 3.1, "3.10 TB"),
            (1024**5 * 3.5, "3.50 PB"),
        ],
    )
    def test_format_bytes_scales_correctly(self, bytes_val, bytes_expected):
        assert format_bytes(bytes_val) == bytes_expected

    @patch("archcare.utils.system.datetime")
    @patch("archcare.utils.system._get_boot_time")
    def test_uptime_formatting(self, mock_boot_time, mock_datetime):
        frozen_boot = datetime(2026, 6, 20, 12, 0, 0)
        mock_boot_time.return_value = frozen_boot

        # Test just now (less than a minute)
        mock_datetime.now.return_value = frozen_boot + timedelta(seconds=30)
        assert get_system_uptime() == "just now"

        # Test minutes only (less than an hour)
        mock_datetime.now.return_value = frozen_boot + timedelta(minutes=45)
        assert get_system_uptime() == "45 minutes"

        # Test hours and minutes
        mock_datetime.now.return_value = frozen_boot + timedelta(hours=3, minutes=15)
        assert get_system_uptime() == "3 hours, 15 minutes"

        # Test days and hours (minutes should be hidden when days > 0)
        mock_datetime.now.return_value = frozen_boot + timedelta(
            days=2, hours=5, minutes=30
        )
        assert get_system_uptime() == "2 days, 5 hours"

        # Test singular phrasing
        mock_datetime.now.return_value = frozen_boot + timedelta(days=1, hours=1)
        assert get_system_uptime() == "1 day, 1 hour"
