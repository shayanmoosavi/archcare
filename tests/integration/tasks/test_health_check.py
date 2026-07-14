"""
Integration tests for health-check task.

Real CLI invocation, real AppContext/config file I/O, real task
orchestration - only the actual subprocess boundary is mocked.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from archcare.cli.app import app
from archcare.utils.system import CommandResult

runner = CliRunner()

_MODULE = "archcare.tasks.health_check"
_SYSTEM_MODULE = "archcare.utils.system"
_PACMAN_MODULE = "archcare.utils.pacman"


def _cmd_result(stdout: str = "", success: bool = True) -> CommandResult:
    return CommandResult(
        command="",
        returncode=0 if success else 1,
        stdout=stdout,
        stderr="",
        success=success,
    )


def _state_json(archcare_home: Path) -> str:
    return (archcare_home / ".local/state/archcare/state.json").read_text()


@pytest.fixture(autouse=True)
def mock_hardware(mocker):
    """
    Defaults to a fully healthy machine - psutil-backed stats would
    otherwise reflect the real test machine's actual state, making
    HealthCheckTask's threshold-gated branching non-deterministic.
    """
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
    mocker.patch(f"{_MODULE}.get_system_uptime", return_value="5 days, 3 hours")


@pytest.fixture(autouse=True)
def mock_subprocess_checks(mocker):
    """
    Defaults to a fully healthy system for the subprocess-backed checks
    too: pacman available, no filesystem errors, no pacman/package
    integrity problems.
    """
    mocker.patch(f"{_PACMAN_MODULE}.check_command_exists", return_value=True)
    mocker.patch(f"{_SYSTEM_MODULE}.run_command", return_value=_cmd_result(""))
    mocker.patch(
        f"{_PACMAN_MODULE}.run_command_with_sudo",
        return_value=_cmd_result("linux: 1000 total files, 0 missing files\n"),
    )


class TestHealthCheckTask:
    def test_all_checks_pass(self, archcare_home: Path):
        runner.invoke(app, ["setup", "config"])

        result = runner.invoke(app, ["task", "run", "health-check"])

        assert result.exit_code == 0
        assert "All health checks passed" in result.output

        # State file updated
        state = _state_json(archcare_home)
        assert "health-check" in state
        assert '"last_status": "success"' in state

    def test_critical_disk_usage_fails(self, mocker, archcare_home: Path):
        # Simulate high disk usage
        mocker.patch(
            f"{_MODULE}.get_disk_usage",
            return_value={"percent": 95.0, "free": 10_000_000_000},
        )

        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "health-check", "--verbose"])

        assert result.exit_code == 1  # Failure for critical
        assert "critical" in result.output.lower()
        assert '"last_status": "failure"' in _state_json(archcare_home)
        assert "Disk usage at 95.0%" in result.output

    def test_warning_level_disk_usage_is_partial(self, mocker, archcare_home: Path):
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
        assert '"last_status": "partial"' in _state_json(archcare_home)

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

    def test_filesystem_errors_escalate_to_critical(self, mocker, archcare_home: Path):
        """Verify that detected filesystem errors result in a critical failure."""
        mocker.patch(
            f"{_SYSTEM_MODULE}.run_command",
            return_value=_cmd_result(
                "EXT4-fs error (device nvme0n1p2): ext4_lookup: deleted inode referenced"
            ),
        )

        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "health-check", "--verbose"])

        assert result.exit_code == 1  # Critical issues result in failure (exit 1)
        assert "critical issue" in result.output.lower()
        assert "1 filesystem error(s) detected" in result.output
        assert '"last_status": "failure"' in _state_json(archcare_home)

    def test_pacman_and_package_issues_escalate_to_critical(
        self, mocker, archcare_home: Path
    ):
        """Verify package manager degradation is caught as a critical issue."""

        def _route(command, **_):
            if command[:2] == ["pacman", "-Dk"]:
                return _cmd_result("error: could not open database\n", success=False)
            if command[:2] == ["pacman", "-Qk"]:
                return _cmd_result(
                    "linux: 1000 total files, 5 missing files\n", success=False
                )
            return _cmd_result("")

        mocker.patch(f"{_PACMAN_MODULE}.run_command", side_effect=_route)
        mocker.patch(
            f"{_PACMAN_MODULE}.run_command_with_sudo",
            side_effect=_route,
        )

        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "health-check", "--verbose"])

        assert result.exit_code == 1
        assert "critical issue" in result.output.lower()
        assert '"last_status": "failure"' in _state_json(archcare_home)
