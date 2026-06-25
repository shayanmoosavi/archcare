"""Unit tests for TaskService."""

import pytest

from archcare.services.exceptions import (
    InvalidTaskTypeError,
    TaskNotFoundError,
    TasksFileEmptyError,
)
from archcare.services.task_service import TaskService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _service(mock_executor) -> TaskService:
    return TaskService(mock_executor)


# ---------------------------------------------------------------------------
# run_task
# ---------------------------------------------------------------------------


class TestRunTask:
    def test_raises_when_tasks_file_is_empty(self, mock_executor, empty_tasks_config):
        mock_executor.config_loader.load_tasks.return_value = empty_tasks_config
        with pytest.raises(TasksFileEmptyError):
            _service(mock_executor).run_task("test-manual-task")

    def test_raises_for_unknown_task_name(self, mock_executor):
        with pytest.raises(TaskNotFoundError) as exc_info:
            _service(mock_executor).run_task("does-not-exist")
        assert exc_info.value.task_name == "does-not-exist"

    def test_response_carries_correct_task_name(self, mock_executor, mock_task_result):
        mock_executor.execute_task.return_value = mock_task_result
        response = _service(mock_executor).run_task("test-manual-task")
        assert response.task_name == "test-manual-task"

    def test_response_outcome_is_executor_result(self, mock_executor, mock_task_result):
        mock_executor.execute_task.return_value = mock_task_result
        response = _service(mock_executor).run_task("test-manual-task")
        assert response.outcome == mock_task_result

    def test_is_interactive_without_archcare_user(
        self, mock_executor, mock_task_result, monkeypatch
    ):
        monkeypatch.delenv("ARCHCARE_USER", raising=False)
        mock_executor.execute_task.return_value = mock_task_result
        response = _service(mock_executor).run_task("test-auto-task")
        assert response.is_interactive is True

    def test_not_interactive_when_archcare_user_is_set(
        self, mock_executor, mock_task_result, monkeypatch
    ):
        monkeypatch.setenv("ARCHCARE_USER", "alice")
        mock_executor.execute_task.return_value = mock_task_result
        response = _service(mock_executor).run_task("test-auto-task")
        assert response.is_interactive is False

    def test_force_flag_is_forwarded_to_executor(self, mock_executor, mock_task_result):
        mock_executor.execute_task.return_value = mock_task_result
        _service(mock_executor).run_task("test-manual-task", force=True)
        mock_executor.execute_task.assert_called_once_with("test-manual-task", True)

    def test_force_false_by_default(self, mock_executor, mock_task_result):
        mock_executor.execute_task.return_value = mock_task_result
        _service(mock_executor).run_task("test-manual-task")
        mock_executor.execute_task.assert_called_once_with("test-manual-task", False)
