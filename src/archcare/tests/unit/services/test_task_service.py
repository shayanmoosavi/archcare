"""Unit tests for TaskService."""

import pytest

from archcare.config import TasksConfig
from archcare.services import TaskService
from archcare.services.exceptions import (
    InvalidTaskTypeError,
    TaskNotFoundError,
    TasksFileEmptyError,
)

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


# ---------------------------------------------------------------------------
# list_tasks
# ---------------------------------------------------------------------------


class TestListTasks:
    def test_raises_when_tasks_file_is_empty(self, mock_executor, empty_tasks_config):
        mock_executor.config_loader.load_tasks.return_value = empty_tasks_config
        with pytest.raises(TasksFileEmptyError):
            _service(mock_executor).list_tasks()

    def test_returns_all_enabled_tasks_with_no_filter(
        self, mock_executor, tasks_config
    ):
        response = _service(mock_executor).list_tasks()
        assert set(response.tasks.keys()) == set(
            tasks_config.get_enabled_tasks().keys()
        )
        assert response.filtered_by is None

    def test_filters_to_automated_tasks(self, mock_executor):
        response = _service(mock_executor).list_tasks(task_type="automated")
        assert all(str(cfg.task_type) == "automated" for cfg in response.tasks.values())
        assert response.filtered_by == "automated"

    def test_filters_to_manual_tasks(self, mock_executor):
        response = _service(mock_executor).list_tasks(task_type="manual")
        assert all(str(cfg.task_type) == "manual" for cfg in response.tasks.values())
        assert response.filtered_by == "manual"

    def test_raises_for_invalid_task_type(self, mock_executor):
        with pytest.raises(InvalidTaskTypeError) as exc_info:
            _service(mock_executor).list_tasks(task_type="nonexistant")
        assert exc_info.value.task_type == "nonexistant"

    def test_disabled_tasks_excluded_from_default_list(
        self, mock_executor, automated_task, disabled_task
    ):
        config_with_disabled = TasksConfig(
            tasks={
                automated_task.name: automated_task,
                disabled_task.name: disabled_task,
            }
        )
        mock_executor.config_loader.load_tasks.return_value = config_with_disabled
        response = _service(mock_executor).list_tasks()
        assert disabled_task.name not in response.tasks
        assert automated_task.name in response.tasks


# ---------------------------------------------------------------------------
# get_task_status
# ---------------------------------------------------------------------------


class TestGetTaskStatus:
    def test_raises_when_tasks_file_is_empty(self, mock_executor, empty_tasks_config):
        mock_executor.config_loader.load_tasks.return_value = empty_tasks_config
        with pytest.raises(TasksFileEmptyError):
            _service(mock_executor).get_task_status()

    def test_raises_for_unknown_task_name(self, mock_executor):
        with pytest.raises(TaskNotFoundError):
            _service(mock_executor).get_task_status(task_name="does-not-exist")

    def test_single_task_returns_one_schedule_entry(self, mock_executor):
        response = _service(mock_executor).get_task_status(task_name="test-auto-task")
        assert len(response.schedule_info) == 1
        assert response.schedule_info[0].task_name == "test-auto-task"

    def test_single_task_has_no_summary(self, mock_executor):
        response = _service(mock_executor).get_task_status(task_name="test-auto-task")
        assert response.summary is None

    def test_all_tasks_returns_one_entry_per_enabled_task(
        self, mock_executor, tasks_config
    ):
        response = _service(mock_executor).get_task_status()
        enabled = tasks_config.get_enabled_tasks()
        assert len(response.schedule_info) == len(enabled)

    def test_all_tasks_includes_summary(self, mock_executor):
        response = _service(mock_executor).get_task_status()
        assert response.summary is not None
        assert "total" in response.summary
        assert "due" in response.summary

    def test_due_only_flag_is_reflected_in_response(self, mock_executor):
        response = _service(mock_executor).get_task_status(due_only=True)
        assert response.due_only is True

    def test_due_only_returns_only_due_tasks(self, mock_executor):
        # Fresh state means both tasks have never run → both are due
        response = _service(mock_executor).get_task_status(due_only=True)
        assert all(info.is_due for info in response.schedule_info)
