"""Unit tests for BaseTask.run() method."""

from dataclasses import dataclass

import pytest

from archcare.config import AppSettings, SkipReason, TaskConfig, TaskStatus
from archcare.core.models import TaskResult
from archcare.tasks import BaseTask

pytestmark = pytest.mark.usefixtures("no_task_logging")

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app_settings(mocker, tmp_path):
    """Provide a minimal AppSettings instance."""
    mocker.patch.object(AppSettings, "home_dir", return_value=tmp_path)
    return AppSettings()


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


@dataclass
class TaskContext:
    """A context object to inject into DummyTask"""

    pre_check_result: bool = True
    pre_check_msg: str = ""
    should_run_result: bool = True
    should_run_msg: str = ""
    should_run_skip_reason: SkipReason | None = None
    execute_exception: Exception | None = None
    execute_result_status: TaskStatus = TaskStatus.SUCCESS


class DummyTask(BaseTask):
    """
    A programmable dummy task to verify BaseTask's Template Method pattern.
    Records the exact order of method calls during execution.
    """

    def __init__(self, config: TaskConfig, settings: AppSettings, context: TaskContext):
        super().__init__(config, settings)
        self.calls: list[str] = []
        self._context: TaskContext = context

    def pre_check(self) -> tuple[bool, str]:
        self.calls.append("pre_check")
        return self._context.pre_check_result, self._context.pre_check_msg

    def should_run(self) -> tuple[bool, str, SkipReason | None]:
        self.calls.append("should_run")
        return (
            self._context.should_run_result,
            self._context.should_run_msg,
            self._context.should_run_skip_reason,
        )

    def execute(self) -> TaskResult:
        self.calls.append("execute")
        if self._context.execute_exception:
            raise self._context.execute_exception

        result = TaskResult(
            status=self._context.execute_result_status,
            message="Dummy task execution successful.",
        )
        return self.create_result(result)

    def post_execute(self, result: TaskResult) -> None:
        self.calls.append("post_execute")

    def rollback(self) -> None:
        self.calls.append("rollback")


# ---------------------------------------------------------------------------
# BaseTask.run
# ---------------------------------------------------------------------------


class TestBaseTaskRun:
    def test_successful_execution_path(self, automated_task, app_settings):
        """
        Test the happy path: pre_check passes, execute succeeds, no rollback.
        """
        context = TaskContext()
        task = DummyTask(automated_task, app_settings, context)
        result = task.run()

        assert result.status == TaskStatus.SUCCESS

        # Verify strict order of operations
        assert task.calls == ["pre_check", "should_run", "execute", "post_execute"]

    def test_pre_check_fail_skips_execution_with_dependency_failed(
        self, automated_task, app_settings
    ):
        """
        Test that pre_check failure skips execution with SKIPPED status
        and SkipReason.DEPENDENCY_FAILED.
        """
        context = TaskContext(
            pre_check_result=False, pre_check_msg="pacman not available"
        )
        task = DummyTask(
            automated_task,
            app_settings,
            context,
        )
        result = task.run()

        # Verify result status and skip reason
        assert result.status == TaskStatus.SKIPPED
        assert result.skip_reason == SkipReason.DEPENDENCY_FAILED
        assert "pacman not available" in result.message

        # Verify strict order of operations
        assert task.calls == ["pre_check"]

    def test_false_should_run_skips_execution(self, automated_task, app_settings):
        """
        Test that a false should_run result skips execution with SKIPPED status
        """
        context = TaskContext(
            should_run_result=False,
            should_run_msg="Nothing to do",
            should_run_skip_reason=SkipReason.NO_WORK_NEEDED,
        )
        task = DummyTask(
            automated_task,
            app_settings,
            context,
        )
        result = task.run()

        # Verify result status and skip reason
        assert result.status == TaskStatus.SKIPPED
        assert "Nothing to do" in result.message

        # Verify strict order of operations
        assert task.calls == ["pre_check", "should_run"]

    def test_task_fails_when_execute_fails(self, automated_task, app_settings):
        """
        Test that task fails with FAILURE (or PARTIAL depending on the implementation)
        status when execute gracefully fails
        """
        context = TaskContext(
            execute_result_status=TaskStatus.FAILURE,
        )
        task = DummyTask(
            automated_task,
            app_settings,
            context,
        )
        result = task.run()

        # Verify result status
        assert result.status != TaskStatus.SUCCESS

        # Verify strict order of operations (same as success workflow)
        assert task.calls == ["pre_check", "should_run", "execute", "post_execute"]

    def test_rollback_attempted_when_execute_raises(self, automated_task, app_settings):
        """
        Test that rollback is attempted when execute raises an exception
        """
        context = TaskContext(
            should_run_result=True,
            execute_exception=RuntimeError("Crash and burn"),
        )
        task = DummyTask(
            automated_task,
            app_settings,
            context,
        )
        result = task.run()

        # Verify result status and error message
        assert result.status == TaskStatus.FAILURE
        assert result.error is not None
        assert "Crash and burn" in result.message

        # Verify strict order of operations
        assert task.calls == [
            "pre_check",
            "should_run",
            "execute",
            "rollback",
        ]
