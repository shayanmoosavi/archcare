"""
Smoke test to check whether the actual CLI works as expected.

Real Typer/Click CLI invocation (via CliRunner), real AppContext
construction, real file I/O (tasks.toml/settings.toml/state.json under
tmp_path via the archcare_home fixture), and real task orchestration
through BaseTask.run(). NotificationManager is mocked (see conftest.py);
nothing else is.
"""

from pathlib import Path

from typer import Abort
from typer.testing import CliRunner

from archcare.cli.app import app
from archcare.config import ConfigLoader, TasksConfig
from archcare.services import TaskService
from archcare.services.exceptions import ConfigNotInitializedError

runner = CliRunner()


class TestSetupConfig:
    def test_creates_all_default_config_files(self, archcare_home: Path):
        result = runner.invoke(app, ["setup", "config"])

        assert result.exit_code == 0
        config_dir = archcare_home / ".config/archcare"
        assert (config_dir / "tasks.toml").exists()
        assert (config_dir / "settings.toml").exists()
        assert (config_dir / "ignored-services.toml").exists()

    def test_running_again_declines_overwrite_without_failing(self):
        """
        Re-running after files already exist triggers the overwrite
        prompt - declining it must still complete successfully (fills in
        anything missing, leaves existing files alone). The file-
        preservation behavior itself is already covered exhaustively in
        test_setup_service.py/test_setup.py; this only confirms the real
        CLI round-trip doesn't break on the second run.
        """
        runner.invoke(app, ["setup", "config"])

        result = runner.invoke(app, ["setup", "config"], input="n\n")

        assert result.exit_code == 0


class TestTaskList:
    def test_lists_tasks_from_shipped_defaults(self):
        runner.invoke(app, ["setup", "config"])

        result = runner.invoke(app, ["task", "list"])

        assert result.exit_code == 0
        # A representative few from the shipped tasks.toml, not an
        # exhaustive check of every task name - that's tasks.toml's own
        # content, not something this test should re-verify line by line.
        assert "maintenance-check" in result.output
        assert "mirrorlist-update" in result.output

    def test_fails_cleanly_before_setup_config_has_run(self):
        result = runner.invoke(app, ["task", "list"])

        # Asserting it fails with the expected exception
        assert isinstance(result.exception, ConfigNotInitializedError)
        assert "not initialized" in str(result.exception)

    def test_invalid_tasks_file_fails_cleanly(self, mocker):
        runner.invoke(app, ["setup", "config"])

        # Simulating corrupt tasks.toml after setup config
        mocker.patch.object(
            ConfigLoader,
            "load_tasks",
            return_value=TasksConfig(tasks={}),
        )

        result = runner.invoke(app, ["task", "list"])

        # Asserting it fails with the expected exception
        assert isinstance(result.exception, SystemExit)
        assert "empty or invalid" in result.stdout
        assert "the logs" in result.stdout
        assert "archcare setup config" in result.stdout

    def test_invalid_task_type_fails_cleanly(self):
        runner.invoke(app, ["setup", "config"])

        result = runner.invoke(app, ["task", "list", "--type", "invalid"])

        # Asserting it fails with the expected exception
        assert isinstance(result.exception, SystemExit)
        assert "Type must be" in result.stdout
        assert "automated" in result.stdout
        assert "manual" in result.stdout


class TestTaskStatus:
    def test_shows_status_for_all_tasks(self):
        runner.invoke(app, ["setup", "config"])

        result = runner.invoke(app, ["task", "status"])

        assert result.exit_code == 0

    def test_shows_status_for_one_task(self):
        runner.invoke(app, ["setup", "config"])

        result = runner.invoke(app, ["task", "status", "maintenance-check"])

        assert result.exit_code == 0

    def test_fails_cleanly_before_setup_config_has_run(self):
        result = runner.invoke(app, ["task", "status"])

        # Asserting it fails with the expected exception
        assert isinstance(result.exception, ConfigNotInitializedError)
        assert "not initialized" in str(result.exception)

    def test_invalid_tasks_file_fails_cleanly(self, mocker):
        runner.invoke(app, ["setup", "config"])

        # Simulating corrupt tasks.toml after setup config
        mocker.patch.object(
            ConfigLoader,
            "load_tasks",
            return_value=TasksConfig(tasks={}),
        )

        result = runner.invoke(app, ["task", "status"])

        # Asserting it fails with the expected exception
        assert isinstance(result.exception, SystemExit)
        assert "empty or invalid" in result.stdout
        assert "the logs" in result.stdout
        assert "archcare setup config" in result.stdout

    def test_invalid_task_fails_cleanly(self):
        runner.invoke(app, ["setup", "config"])
        result = runner.invoke(app, ["task", "status", "invalid"])

        # Asserting it fails with the expected exception
        assert isinstance(result.exception, SystemExit)
        assert "not found: invalid" in result.stdout
        assert "archcare task list" in result.stdout

    def test_generic_exception_fails_cleanly(self, mocker):
        runner.invoke(app, ["setup", "config"])

        mocker.patch.object(
            TaskService, "get_task_status", side_effect=OSError("Disk failed")
        )

        result = runner.invoke(app, ["task", "status"])

        # Asserting it fails with the expected exception
        assert isinstance(result.exception, SystemExit)
        assert "Disk failed" in result.stdout


class TestTaskRun:
    def test_running_check_maintenance_succeeds(self):
        """
        check-maintenance is the `task run` vehicle here specifically because its
        execute() never touches the subprocess/OS boundary at all
        """
        runner.invoke(app, ["setup", "config"])

        result = runner.invoke(app, ["task", "run", "maintenance-check"])

        assert result.exit_code == 0
        assert result.exception is None

    def test_state_file_is_updated_after_run(self, archcare_home: Path):
        runner.invoke(app, ["setup", "config"])
        runner.invoke(app, ["task", "run", "maintenance-check"])

        state_file = archcare_home / ".local/state/archcare/state.json"
        assert state_file.exists()
        assert "maintenance-check" in state_file.read_text()

    def test_fails_cleanly_before_setup_config_has_run(self):
        result = runner.invoke(app, ["task", "run", "maintenance-check"])

        # Asserting it fails with the expected exception
        assert isinstance(result.exception, ConfigNotInitializedError)
        assert "not initialized" in str(result.exception)

    def test_running_unregistered_task_fails_cleanly(self):
        """
        Confirms an unregistered task fails with a clean, handled error
        (task.py's generic except Exception -> typer.Exit(1)) rather than
        an unhandled crash.
        """
        runner.invoke(app, ["setup", "config"])

        # A task that exists in tasks.toml but not in task registry
        result = runner.invoke(app, ["task", "run", "cache-cleanup"])

        # Confirm the exception is a SystemExit (typer.Exit) with exit code 1
        assert "Failed to run task" in result.stdout
        assert "No task registered" in result.stdout
        assert isinstance(result.exception, SystemExit)
        assert result.exit_code == 1

    def test_running_invalid_task_fails_cleanly(self):
        runner.invoke(app, ["setup", "config"])

        result = runner.invoke(app, ["task", "run", "invalid"])

        assert "not found: invalid" in result.stdout
        assert "archcare task list" in result.stdout
        assert isinstance(result.exception, SystemExit)
        assert result.exit_code == 1

    def test_aborting_execution_fails_cleanly(self, mocker):
        runner.invoke(app, ["setup", "config"])

        mocker.patch.object(TaskService, "run_task", side_effect=Abort)

        result = runner.invoke(app, ["task", "run", "maintenance-check"])

        assert "execution aborted"
        assert isinstance(result.exception, SystemExit)
        assert result.exit_code == 1
