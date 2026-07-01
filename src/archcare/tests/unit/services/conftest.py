"""Shared fixtures for service layer unit tests."""

from unittest.mock import MagicMock, Mock

import pytest

from archcare.config import AppState, TasksConfig, TaskStatus
from archcare.core import TaskResult


@pytest.fixture
def mock_task_result() -> Mock:
    """A successful TaskResult mock."""
    result = Mock(spec=TaskResult)
    result.status = TaskStatus.SUCCESS
    result.is_success.return_value = True
    result.is_partial.return_value = False
    result.is_skipped.return_value = False
    result.is_failed.return_value = False
    result.details = {}
    return result


@pytest.fixture
def mock_executor(tasks_config: TasksConfig, fresh_state: AppState) -> MagicMock:
    """
    Mock TaskExecutor with a two-task config and fresh state.

    Used by service-layer tests that should never touch the filesystem.
    """
    executor = MagicMock()
    executor.config_loader.load_tasks.return_value = tasks_config
    executor.state = fresh_state
    return executor
