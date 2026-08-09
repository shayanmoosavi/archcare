"""
Integration tests for health-check task.

Real CLI invocation, real AppContext/config file I/O, real task
orchestration - only the actual subprocess boundary is mocked.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from archcare.cli.app import app
from archcare.utils.info_models import CpuInfo, DiskUsageInfo, MemoryInfo
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
        return_value=DiskUsageInfo(
            percent=45.0,
            free=500_000_000_000,
            total=1_000_000_000_000,
        ),
    )
    mocker.patch(
        f"{_MODULE}.get_memory_info",
        return_value=MemoryInfo(
            percent=35.0,
            available=8_000_000_000,
            swap_percent=10.0,
        ),
    )
    mocker.patch(
        f"{_MODULE}.get_cpu_info",
        return_value=CpuInfo(
            percent=12.0,
            cores=8,
            load_avg=(0.5, 0.6, 0.7),
        ),
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
    mocker.patch(f"{_PACMAN_MODULE}.run_command", return_value=_cmd_result(""))
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
            return_value=DiskUsageInfo(percent=95.0, free=10_000_000_000),
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
            return_value=MemoryInfo(
                percent=85.0,
                available=2_000_000_000,
                swap_percent=0.0,
            ),
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
            return_value=CpuInfo(
                percent=12.0,
                cores=8,
                load_avg=(17.5, 5.0, 4.0),
            ),
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
            return_value=MemoryInfo(
                percent=45.0,  # RAM is healthy
                available=8_000_000_000,
                swap_percent=65.0,  # Swap is high
            ),
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


class TestHealthCheckProgressReporting:
    """
    Exercises the real AppContext -> TaskExecutor -> HealthCheckTask wiring
    end-to-end - the one place that actually proves progress=RichProgress()
    reaches BaseTask.report_progress(), not just that the unit-level pieces
    are individually correct in isolation.
    """

    def test_progress_started_with_check_count_total(self, mock_progress):
        runner.invoke(app, ["setup", "config"])

        runner.invoke(app, ["task", "run", "health-check"])

        mock_progress.return_value.start.assert_called_once_with(total=7)

    def test_progress_advanced_once_per_check(self, mock_progress):
        runner.invoke(app, ["setup", "config"])

        runner.invoke(app, ["task", "run", "health-check"])

        assert mock_progress.return_value.advance.call_count == 7

    def test_progress_stopped_after_run(self, mock_progress):
        runner.invoke(app, ["setup", "config"])

        runner.invoke(app, ["task", "run", "health-check"])

        mock_progress.return_value.stop.assert_called_once()

    def test_packages_check_paused_for_sudo_prompt(self, mock_progress):
        """
        The package-file-integrity check is the one that shells out via
        sudo - progress.pause() must wrap exactly that call so a real sudo
        prompt wouldn't be rendered underneath the live progress display.
        """
        runner.invoke(app, ["setup", "config"])

        runner.invoke(app, ["task", "run", "health-check"])

        mock_progress.return_value.pause.assert_called_once()

    def test_progress_lifecycle_holds_even_on_critical_failure(self, mocker, mock_progress):
        """
        A critical issue (e.g. high disk usage) still runs every check to
        completion - it doesn't raise, it accumulates into `issues` - so
        the full start/advance x7/stop/pause sequence should still fire
        exactly as in the all-healthy case.
        """
        mocker.patch(
            f"{_MODULE}.get_disk_usage",
            return_value=DiskUsageInfo(percent=95.0, free=10_000_000_000),
        )

        runner.invoke(app, ["setup", "config"])
        runner.invoke(app, ["task", "run", "health-check"])

        mock_progress.return_value.start.assert_called_once_with(total=7)
        assert mock_progress.return_value.advance.call_count == 7
        mock_progress.return_value.stop.assert_called_once()
