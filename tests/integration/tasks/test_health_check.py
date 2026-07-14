"""
Integration tests for health-check task.

Real CLI invocation, real AppContext/config file I/O, real task
orchestration - only the actual subprocess boundary is mocked.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from archcare.cli.app import app

runner = CliRunner()

_MODULE = "archcare.tasks.health_check"


@pytest.fixture(autouse=True)
def mock_hardware(mocker):
    """Mock all hardware queries to return healthy values by default."""
    mocker.patch(
        f"{_MODULE}.get_disk_usage",
        return_value={
            "percent": 45.0,
            "free": 500_000_000_000,
            "total": 1_000_000_000_000,
        },
    )
    mocker.patch(
        f"{_MODULE}.get_memory_info",
        return_value={
            "percent": 35.0,
            "available": 8_000_000_000,
            "swap_percent": 10.0,
        },
    )
    mocker.patch(
        f"{_MODULE}.get_cpu_info",
        return_value={"percent": 12.0, "count": 8, "load_avg": (0.5, 0.6, 0.7)},
    )
    mocker.patch(f"{_MODULE}.check_filesystem_errors", return_value=[])
    mocker.patch(f"{_MODULE}.check_pacman_database", return_value=(True, "Healthy"))
    mocker.patch(f"{_MODULE}.check_package_files", return_value=(True, "All good"))
    mocker.patch(f"{_MODULE}.get_system_uptime", return_value="5 days, 3 hours")


class TestHealthCheckTask:
    def test_all_checks_pass(self, archcare_home: Path):
        runner.invoke(app, ["setup", "config"])

        result = runner.invoke(app, ["task", "run", "health-check"])

        assert result.exit_code == 0
        assert "All health checks passed" in result.output

        # State file updated
        state = (archcare_home / ".local/state/archcare/state.json").read_text()
        assert "health-check" in state
        assert '"last_status": "success"' in state

    def test_critical_issue_reported(self, mocker):
        # Simulate high disk usage
        mocker.patch(
            f"{_MODULE}.get_disk_usage",
            return_value={"percent": 95.0, "free": 10_000_000_000},
        )

        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "health-check", "--verbose"])

        assert result.exit_code == 1  # Failure for critical
        assert "critical" in result.output.lower()
        assert "Disk usage at 95.0%" in result.output

    def test_warnings_only_partial_success(self, mocker):
        mocker.patch(
            f"{_MODULE}.get_memory_info",
            return_value={
                "percent": 85.0,
                "available": 2_000_000_000,
                "swap_percent": 0.0,
            },
        )

        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "health-check"])

        assert result.exit_code == 0  # Partial is treated as success for exit code
        assert "warning" in result.output.lower()

    def test_cpu_load_average_warning(self, mocker):
        """Verify load averages exceeding cpu_count * 2 trigger a warning."""
        mocker.patch(
            f"{_MODULE}.get_cpu_info",
            # 8 cores * 2 = 16 threshold. 17.5 should trigger the warning.
            return_value={"percent": 12.0, "count": 8, "load_avg": (17.5, 5.0, 4.0)},
        )

        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "health-check", "--verbose"])

        assert result.exit_code == 0  # Warnings result in a partial success (exit 0)
        assert "warning" in result.output.lower()
        assert "High load average 17.50" in result.output

    def test_high_swap_usage_warning(self, mocker):
        """Verify high swap usage triggers a warning even if RAM is healthy."""
        mocker.patch(
            f"{_MODULE}.get_memory_info",
            return_value={
                "percent": 45.0,  # RAM is healthy
                "available": 8_000_000_000,
                "swap_percent": 65.0,  # Swap is high
            },
        )

        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "health-check", "--verbose"])

        assert result.exit_code == 0
        assert "High swap usage at 65.0%" in result.output

    def test_filesystem_errors_escalate_to_critical(self, mocker):
        """Verify that detected filesystem errors result in a critical failure."""
        mocker.patch(
            f"{_MODULE}.check_filesystem_errors",
            return_value=[
                "EXT4-fs error (device nvme0n1p2): ext4_lookup: deleted inode referenced"
            ],
        )

        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "health-check", "--verbose"])

        assert result.exit_code == 1  # Critical issues result in failure (exit 1)
        assert "critical issue" in result.output.lower()
        assert "1 filesystem error(s) detected" in result.output

    def test_pacman_and_package_issues_escalate_to_critical(self, mocker):
        """Verify package manager degradation is caught as a critical issue."""
        mocker.patch(
            f"{_MODULE}.check_pacman_database",
            return_value=(False, "Database lock file found: /var/lib/pacman/db.lck"),
        )
        mocker.patch(
            f"{_MODULE}.check_package_files",
            return_value=(False, "Missing files detected in coreutils"),
        )

        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "health-check", "--verbose"])

        assert result.exit_code == 1
        assert "critical issue" in result.output.lower()
        assert "Database lock file found" in result.output
        assert "Missing files detected in coreutils" in result.output
