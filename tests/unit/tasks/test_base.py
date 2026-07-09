"""Unit tests for BaseTask.run() method."""

from dataclasses import dataclass

import pytest

from archcare.config import AppSettings, SkipReason, TaskConfig, TaskStatus
from archcare.core import TaskResult
from archcare.tasks import BaseTask

pytestmark = pytest.mark.usefixtures("no_task_logging")

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app_settings(mocker, tmp_path) -> AppSettings:
    """Provide a minimal AppSettings instance."""
    mocker.patch.object(AppSettings, "home_dir", property(lambda _: tmp_path))
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
    rollback_exception: Exception | None = None


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
        if self._context.rollback_exception:
            raise self._context.rollback_exception


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


class TestRunWorkflow:
    def test_successful_execution_path(
        self, automated_task: TaskConfig, app_settings: AppSettings
    ):
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
        self, automated_task: TaskConfig, app_settings: AppSettings
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

    def test_false_should_run_skips_execution(
        self, automated_task: TaskConfig, app_settings: AppSettings
    ):
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

    def test_false_should_run_with_no_skip_reason(
        self, automated_task: TaskConfig, app_settings: AppSettings
    ):
        """
        Test that a false should_run result with no skip reason still produces
        a valid skipped result.
        """
        context = TaskContext(should_run_result=False, should_run_msg="Not due yet")
        task = DummyTask(automated_task, app_settings, context)

        result = task.run()

        assert result.status == TaskStatus.SKIPPED
        assert result.skip_reason is None
        assert "Not due yet" in result.message

    @pytest.mark.parametrize(
        "execute_result_status", [TaskStatus.FAILURE, TaskStatus.PARTIAL]
    )
    def test_not_success_execute_status_flows_through(
        self,
        automated_task: TaskConfig,
        app_settings: AppSettings,
        execute_result_status,
    ):
        """
        Test that task with FAILURE (or PARTIAL depending on the implementation)
        status flows through to the result status when execute gracefully fails.
        """
        context = TaskContext(
            execute_result_status=execute_result_status,
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

    def test_rollback_attempted_when_execute_raises(
        self, automated_task: TaskConfig, app_settings: AppSettings
    ):
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

    def test_rollback_failure_does_not_prevent_result_return(
        self, automated_task: TaskConfig, app_settings: AppSettings
    ):
        """
        The inner try/except around rollback() must swallow a rollback
        failure (logged as critical) without letting it propagate or
        replace the original execute() failure being reported.
        """
        context = TaskContext(
            execute_exception=RuntimeError("Crash and burn"),
            rollback_exception=OSError("rollback also failed"),
        )
        task = DummyTask(automated_task, app_settings, context)

        result = task.run()  # must not raise, despite rollback() raising

        assert result.status == TaskStatus.FAILURE
        assert "Crash and burn" in result.message  # original error, not rollback's
        assert task.calls == ["pre_check", "should_run", "execute", "rollback"]


# ---------------------------------------------------------------------------
# create_result
# ---------------------------------------------------------------------------


class TestCreateResult:
    """
    Isolated tests of create_result()'s own timing logic, decoupled from
    the full run() workflow and from set_start_time()'s default-argument
    behavior. time.time() is frozen to two known values so duration_seconds
    can be asserted exactly, not just "some positive number" - calling
    set_start_time()/create_result() directly (bypassing run()) also avoids
    loguru's own internal timestamping consuming extra values from the mocked
    sequence.
    """

    def test_duration_seconds_reflects_elapsed_time(
        self, automated_task, app_settings, mocker
    ):
        mocker.patch("archcare.tasks.base.time.time", side_effect=[1000.0, 1000.5])
        context = TaskContext()
        task = DummyTask(automated_task, app_settings, context)

        task.set_start_time()  # consumes the first mocked value: 1000.0
        result = task.create_result(
            TaskResult(status=TaskStatus.SUCCESS, message="done")
        )  # consumes the second: 1000.5

        assert result.duration_seconds == pytest.approx(0.5)


# -----------------------------------------------------------------------------
# String representations
# -----------------------------------------------------------------------------


class TestStringRepresentations:
    def test_str_includes_class_name_and_task_name(self, automated_task, app_settings):
        task = DummyTask(automated_task, app_settings, TaskContext())

        assert str(task) == f"DummyTask(name={automated_task.name})"

    def test_repr_includes_key_fields(self, automated_task, app_settings):
        task = DummyTask(automated_task, app_settings, TaskContext())

        result = repr(task)

        assert "DummyTask" in result
        assert automated_task.name in result
        assert str(automated_task.task_type) in result
        assert str(automated_task.frequency) in result
