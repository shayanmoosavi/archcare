"""
Integration tests for failed-services task.

Real CLI invocation, real AppContext/config file I/O, real task
orchestration - only the actual subprocess boundary is mocked.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from archcare.cli.app import app
from archcare.utils.system import CommandResult

runner = CliRunner()

_MODULE = "archcare.tasks.failed_services"
_SYSTEM_MODULE = "archcare.utils.system"


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _cmd_result(stdout: str = "", success: bool = True) -> CommandResult:
    return CommandResult(
        command="",
        returncode=0 if success else 1,
        stdout=stdout,
        stderr="",
        success=success,
    )


def _fake_run_command(command, **_):
    """
    Routes on the real command shape (systemctl's own subcommand, at
    index 1, since run_systemctl always builds ["systemctl"] + args) so
    each caller gets realistically-shaped output to parse for real.
    """
    subcommand = command[1] if len(command) > 1 else ""

    if subcommand == "list-units" and "--state=failed" in command:
        return _cmd_result("nginx.service     loaded failed failed nginx web server\n")
    if subcommand == "status":
        return _cmd_result(
            "   Loaded: loaded (/usr/lib/systemd/system/nginx.service; enabled)\n"
            "   Active: failed (Result: exit-code)\n"
            " Main PID: 1234 (code=exited, status=1/FAILURE)\n"
        )
    if subcommand == "list-units":  # description lookup, no --state=failed
        return _cmd_result("nginx.service loaded failed failed nginx web server")
    if command[0] == "journalctl":
        return _cmd_result("log line 1\nlog line 2\n")
    return _cmd_result()


def _state_json(archcare_home: Path) -> str:
    return (archcare_home / ".local/state/archcare/state.json").read_text()


@pytest.fixture(autouse=True)
def mock_check_command_exists(mocker):
    """Defaults to systemctl being available - overridden per test for
    the pre_check-failure case."""
    return mocker.patch(f"{_MODULE}.check_command_exists", return_value=True)


@pytest.fixture(autouse=True)
def mock_run_command(mocker):
    return mocker.patch(f"{_SYSTEM_MODULE}.run_command", side_effect=_fake_run_command)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFailedServicesTask:
    def test_reports_failed_services(self):
        runner.invoke(app, ["setup", "config"])

        result = runner.invoke(app, ["task", "run", "failed-services"])

        assert result.exit_code == 0
        assert "nginx.service" in result.output

    def test_reports_failed_services_verbose_mode(self):
        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "run", "failed-services", "--verbose"])

        assert result.exit_code == 0
        assert "nginx.service" in result.output
        assert "nginx web server" in result.output
        assert "log line 1" in result.output
        assert "log line 2" in result.output

    def test_skips_when_no_failed_services(self, archcare_home: Path, mock_run_command):
        mock_run_command.side_effect = None
        mock_run_command.return_value = _cmd_result("")  # no failed units at all
        runner.invoke(app, ["setup", "config"])

        result = runner.invoke(app, ["task", "run", "failed-services"])

        assert result.exit_code == 0
        assert '"last_status": "skipped"' in _state_json(archcare_home)
        assert '"skip_reason": "no_work_needed"' in _state_json(archcare_home)

    def test_ignored_services_are_filtered_out(self, archcare_home: Path):
        runner.invoke(app, ["setup", "config"])
        ignored_path = archcare_home / ".config/archcare/ignored-services.toml"
        ignored_path.write_text('services = ["nginx.service"]\n')

        result = runner.invoke(app, ["task", "run", "failed-services"])

        # nginx.service is the only "failed" unit in the mocked output,
        # and it's ignored - nothing left to report, so the task skips.
        assert result.exit_code == 0
        assert '"skip_reason": "no_work_needed"' in _state_json(archcare_home)

    def test_pre_check_fails_cleanly_when_systemctl_missing(
        self, archcare_home: Path, mock_check_command_exists
    ):
        mock_check_command_exists.return_value = False
        runner.invoke(app, ["setup", "config"])

        result = runner.invoke(app, ["task", "run", "failed-services"])

        assert result.exit_code == 0  # a skip is still a "successful" run
        assert '"skip_reason": "dependency_failed"' in _state_json(archcare_home)
