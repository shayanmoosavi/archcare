"""
Integration tests for the shared task-execution pipeline (`TaskExecutor`).

Real CLI invocation, real AppContext/config I/O, real task orchestration — only the actual
subprocess / OS boundary is mocked.

What is covered here:

- the *not due* gate: the prompt, the two answers, and `--force`,
- the *disabled* gate: the notification, the prompt, the two answers, `--force`,
- the *headless* (systemd timer) branch of both gates, which skips on its own instead of asking a
    question nobody is there to answer,
- the rule that `--force` bypasses the executor's gates but never a task's own
  `should_run()` gate,
- the `next_due` bookkeeping the executor performs per outcome.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from _pytest.monkeypatch import MonkeyPatch
from tomlkit import dumps, parse
from typer.testing import CliRunner

from archcare.cli.app import app
from archcare.utils.info_models import ServiceStatusInfo
from tests.integration.conftest import clean_output, task_state

runner = CliRunner()

# The vehicle task. Chosen because it is a *manual* task (so it is meant to be run by a person, not
# a timer) and because its own `should_run()` gate is distinct from the executor's — which lets the
# "force does not bypass the task's own gate" rule be expressed against the executor rather than
# against any particular task's environment checks.
VEHICLE = "failed-services"
_MODULE = "archcare.tasks.failed_services"

# A failed unit, so the vehicle's own gate lets the run through.
FAILED_UNIT = "nginx.service"


def _disable_vehicle(archcare_home: Path) -> None:
    """Flip `enabled` to false for the vehicle task in the generated `tasks.toml`."""
    tasks_file = archcare_home / ".config/archcare/tasks.toml"
    document = parse(tasks_file.read_text())
    document[VEHICLE]["enabled"] = False
    tasks_file.write_text(dumps(document))


@pytest.fixture(autouse=True)
def mock_vehicle(mocker) -> MagicMock:
    """
    Stub the vehicle task's OS boundary.

    `get_systemd_failed_services` is the single seam that decides whether the task's own gate lets
    the run through, so its call count doubles as the "did the task body actually run?" signal these
    tests need.
    """
    mocker.patch(f"{_MODULE}.check_command_exists", return_value=True)
    failed = mocker.patch(f"{_MODULE}.get_systemd_failed_services", return_value=[FAILED_UNIT])
    mocker.patch(
        f"{_MODULE}.get_service_status",
        return_value=ServiceStatusInfo(
            loaded=True,
            active="failed",
            main_pid=1234,
            description="nginx web server",
        ),
    )
    mocker.patch(f"{_MODULE}.get_service_logs", return_value=[])
    return failed


@pytest.fixture
def headless(monkeypatch: MonkeyPatch, archcare_home: Path) -> None:
    """
    Make the run behave as a systemd timer would.

    `ARCHCARE_USER` is what the CLI reads to decide it is headless, and a headless run takes a
    different branch through both executor gates: it skips on its own instead of asking a question
    nobody is there to answer.

    `archcare_home` is requested explicitly so it is guaranteed to be torn down *before* this
    fixture sets the variable — the shared fixture clears `ARCHCARE_USER` precisely so that only a
    test that asks for headless mode gets it.
    """
    monkeypatch.setenv("ARCHCARE_USER", "archcare-timer")


# ---------------------------------------------------------------------------
# The not-due gate
# ---------------------------------------------------------------------------


class TestExecutorNotDueGate:
    """The schedule gate: a task that is not due yet."""

    def test_a_not_due_task_prompts_before_running(self, archcare_home: Path):
        """Declining the 'Run anyway?' prompt skips the task without running it."""
        runner.invoke(app, ["setup", "config"])
        runner.invoke(app, ["task", "run", VEHICLE])
        assert task_state(archcare_home, VEHICLE)["last_status"] != "skipped"

        result = runner.invoke(app, ["task", "run", VEHICLE], input="n\n")

        assert result.exit_code == 0
        output = clean_output(result.output)
        assert "not due" in output
        assert "Run anyway?" in output
        assert "SKIPPED" in output
        assert task_state(archcare_home, VEHICLE)["skip_reason"] == "user_cancelled"

    @pytest.mark.usefixtures("archcare_home")
    def test_a_not_due_task_does_not_run_when_declined(self, mock_vehicle: MagicMock):
        """The task's own gate is never reached — the executor stops first."""
        runner.invoke(app, ["setup", "config"])
        runner.invoke(app, ["task", "run", VEHICLE])
        mock_vehicle.reset_mock()

        runner.invoke(app, ["task", "run", VEHICLE], input="n\n")

        mock_vehicle.assert_not_called()

    def test_answering_run_anyway_runs_the_task(self, archcare_home: Path, mock_vehicle: MagicMock):
        """Accepting the 'Run anyway?' prompt goes through to the task."""
        runner.invoke(app, ["setup", "config"])
        runner.invoke(app, ["task", "run", VEHICLE])
        mock_vehicle.reset_mock()

        result = runner.invoke(app, ["task", "run", VEHICLE], input="y\n")

        assert result.exit_code == 0
        assert "Run anyway?" in clean_output(result.output)
        mock_vehicle.assert_called()
        assert task_state(archcare_home, VEHICLE)["last_status"] != "skipped"

    @pytest.mark.usefixtures("archcare_home")
    def test_force_runs_a_not_due_task_without_prompting(self, mock_vehicle: MagicMock):
        """`--force` runs a task that is not due, without asking anything."""
        runner.invoke(app, ["setup", "config"])
        runner.invoke(app, ["task", "run", VEHICLE])
        mock_vehicle.reset_mock()

        result = runner.invoke(app, ["task", "run", VEHICLE, "--force"])

        assert result.exit_code == 0
        assert "Run anyway?" not in clean_output(result.output)
        mock_vehicle.assert_called()


# ---------------------------------------------------------------------------
# The disabled gate
# ---------------------------------------------------------------------------


class TestExecutorDisabledGate:
    """The configuration gate: a task the user turned off."""

    def test_a_disabled_task_prompts_before_running(self, archcare_home: Path):
        """A disabled task is announced and then asks before overriding the choice."""
        runner.invoke(app, ["setup", "config"])
        _disable_vehicle(archcare_home)

        result = runner.invoke(app, ["task", "run", VEHICLE], input="n\n")

        assert result.exit_code == 0
        output = clean_output(result.output)
        assert "disabled" in output.lower()
        assert "Run anyway?" in output
        assert "SKIPPED" in output
        assert task_state(archcare_home, VEHICLE)["skip_reason"] == "user_cancelled"

    def test_a_disabled_task_does_not_run_when_declined(
        self, archcare_home: Path, mock_vehicle: MagicMock
    ):
        """Declining leaves the task alone — the whole point of disabling it."""
        runner.invoke(app, ["setup", "config"])
        _disable_vehicle(archcare_home)

        runner.invoke(app, ["task", "run", VEHICLE], input="n\n")

        mock_vehicle.assert_not_called()

    def test_answering_run_anyway_runs_a_disabled_task(
        self, archcare_home: Path, mock_vehicle: MagicMock
    ):
        """Accepting overrides the disable and the task runs."""
        runner.invoke(app, ["setup", "config"])
        _disable_vehicle(archcare_home)

        result = runner.invoke(app, ["task", "run", VEHICLE], input="y\n")

        assert result.exit_code == 0
        assert "disabled" in clean_output(result.output).lower()
        mock_vehicle.assert_called()
        assert task_state(archcare_home, VEHICLE)["last_status"] != "skipped"

    def test_force_runs_a_disabled_task_without_prompting(
        self, archcare_home: Path, mock_vehicle: MagicMock
    ):
        """`--force` overrides the disable outright — no question is asked."""
        runner.invoke(app, ["setup", "config"])
        _disable_vehicle(archcare_home)

        result = runner.invoke(app, ["task", "run", VEHICLE, "--force"])

        assert result.exit_code == 0
        assert "Run anyway?" not in clean_output(result.output)
        mock_vehicle.assert_called()


# ---------------------------------------------------------------------------
# The headless (systemd timer) branch
# ---------------------------------------------------------------------------


class TestExecutorHeadlessGates:
    """
    A headless run skips on its own instead of asking.

    There is nobody at the terminal to answer a prompt, so the executor decides by itself — and it
    records *why* differently, which is the observable difference between the two branches.
    """

    @pytest.mark.usefixtures("headless")
    def test_a_not_due_task_is_skipped_without_a_prompt(
        self, archcare_home: Path, mock_vehicle: MagicMock
    ):
        """The headless branch reports `not_due`, not `user_cancelled`."""
        runner.invoke(app, ["setup", "config"])
        runner.invoke(app, ["task", "run", VEHICLE])
        mock_vehicle.reset_mock()

        result = runner.invoke(app, ["task", "run", VEHICLE])

        assert result.exit_code == 0
        assert task_state(archcare_home, VEHICLE)["skip_reason"] == "not_due"
        mock_vehicle.assert_not_called()

    @pytest.mark.usefixtures("headless")
    def test_a_disabled_task_is_skipped_without_a_prompt(
        self, archcare_home: Path, mock_vehicle: MagicMock
    ):
        """The headless branch reports `disabled`, not `user_cancelled`."""
        runner.invoke(app, ["setup", "config"])
        _disable_vehicle(archcare_home)

        result = runner.invoke(app, ["task", "run", VEHICLE])

        assert result.exit_code == 0
        assert task_state(archcare_home, VEHICLE)["skip_reason"] == "disabled"
        mock_vehicle.assert_not_called()

    @pytest.mark.usefixtures("headless")
    def test_a_disabled_task_has_no_schedule_in_headless_mode(
        self, archcare_home: Path, mock_vehicle: MagicMock
    ):
        """A disabled task has no `next_due` — there is nothing to schedule it for."""
        runner.invoke(app, ["setup", "config"])
        _disable_vehicle(archcare_home)

        runner.invoke(app, ["task", "run", VEHICLE])

        assert task_state(archcare_home, VEHICLE)["next_due"] is None
        mock_vehicle.assert_not_called()


# ---------------------------------------------------------------------------
# What `--force` does not bypass
# ---------------------------------------------------------------------------


class TestExecutorForceScope:
    """`--force` is about the schedule, not about the environment."""

    def test_force_does_not_bypass_the_tasks_own_gate(
        self, archcare_home: Path, mock_vehicle: MagicMock
    ):
        """
        The executor's gates are skipped; the task's own gate still applies.

        The vehicle's `should_run()` reports "nothing to do" when no unit has failed. `--force`
        cannot make that work appear — it only removes the executor's own scheduling questions.
        """
        runner.invoke(app, ["setup", "config"])
        mock_vehicle.return_value = []

        result = runner.invoke(app, ["task", "run", VEHICLE, "--force"])

        assert result.exit_code == 0
        assert "SKIPPED" in result.output
        assert task_state(archcare_home, VEHICLE)["skip_reason"] == "no_work_needed"


# ---------------------------------------------------------------------------
# State bookkeeping
# ---------------------------------------------------------------------------


class TestExecutorNextDue:
    """`next_due` is the executor's contract with the scheduler, per outcome."""

    def test_a_successful_run_advances_the_next_due(self, archcare_home: Path):
        """A completed check slides the schedule forward by the task's frequency."""
        runner.invoke(app, ["setup", "config"])
        runner.invoke(app, ["task", "run", VEHICLE])

        assert task_state(archcare_home, VEHICLE)["next_due"] is not None

    @pytest.mark.usefixtures("headless")
    def test_a_skipped_run_preserves_the_next_due(self, archcare_home: Path):
        """
        A run that stood down does not consume the schedule.

        A skip reason besides `NO_WORK_NEEDED` shouldn't move the schedule forward,
        otherwise, the tasks that were skipped several times in a row will shift the
        next due forever and never run.
        """
        runner.invoke(app, ["setup", "config"])
        runner.invoke(app, ["task", "run", VEHICLE])
        next_due = task_state(archcare_home, VEHICLE)["next_due"]

        runner.invoke(app, ["task", "run", VEHICLE])

        assert task_state(archcare_home, VEHICLE)["next_due"] == next_due

    def test_a_failed_run_preserves_the_next_due(self, archcare_home: Path, mocker):
        """
        A failure does not consume the schedule either.

        The task is still due, so a retry happens without waiting a full frequency — a broken
        package manager should be retried, not postponed.
        """
        runner.invoke(app, ["setup", "config"])
        runner.invoke(app, ["task", "run", VEHICLE])
        next_due = task_state(archcare_home, VEHICLE)["next_due"]

        mocker.patch(
            f"{_MODULE}.get_systemd_failed_services", side_effect=OSError("systemctl died")
        )
        runner.invoke(app, ["task", "run", VEHICLE, "--force"])

        assert task_state(archcare_home, VEHICLE)["last_status"] == "failure"
        assert task_state(archcare_home, VEHICLE)["next_due"] == next_due
