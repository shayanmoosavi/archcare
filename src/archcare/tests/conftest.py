"""Shared fixtures for the Archcare test suite."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock

import pytest

from archcare.config import AppState, TaskConfig, TasksConfig, TaskStatus
from archcare.core.models import TaskResult

# ---------------------------------------------------------------------------
# TaskConfig fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def automated_task() -> TaskConfig:
    """An enabled automated task."""
    return TaskConfig.model_validate(
        {
            "name": "test-auto-task",
            "type": "automated",
            "frequency": 7,
            "description": "A generic automated task",
            "command": "test-auto-task",
            "enabled": True,
        }
    )


@pytest.fixture
def manual_task() -> TaskConfig:
    """An enabled manual task."""
    return TaskConfig.model_validate(
        {
            "name": "test-manual-task",
            "type": "manual",
            "frequency": 30,
            "description": "A generic manual task",
            "command": "test-manual-task",
            "enabled": True,
        }
    )


@pytest.fixture
def disabled_task() -> TaskConfig:
    """A disabled automated task."""
    return TaskConfig.model_validate(
        {
            "name": "test-disabled-task",
            "type": "automated",
            "frequency": 1,
            "description": "A generic disabled automated task",
            "command": "test-disabled-task",
            "enabled": False,
        }
    )


@pytest.fixture
def tasks_config(automated_task, manual_task) -> TasksConfig:
    """Two-task config: one automated, one manual, both enabled."""
    return TasksConfig(
        tasks={
            automated_task.name: automated_task,
            manual_task.name: manual_task,
        }
    )


@pytest.fixture
def empty_tasks_config() -> TasksConfig:
    return TasksConfig(tasks={})


# ---------------------------------------------------------------------------
# AppState fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_state() -> AppState:
    """No tasks have ever run."""
    return AppState()


@pytest.fixture
def state_with_recent_run(automated_task) -> AppState:
    """automated_task ran successfully just now; next_due is 7 days away."""
    state = AppState()
    state.update_task_state(
        task_name=automated_task.name,
        status=TaskStatus.SUCCESS,
        next_due=datetime.now() + timedelta(days=7),
        error=None,
        skip_reason=None,
        skip_message=None,
    )
    return state


@pytest.fixture
def state_with_overdue_run(automated_task) -> AppState:
    """automated_task last ran 10 days ago with a 7-day frequency → overdue."""
    state = AppState()
    state.update_task_state(
        task_name=automated_task.name,
        status=TaskStatus.SUCCESS,
        next_due=datetime.now() - timedelta(days=3),
        error=None,
        skip_reason=None,
        skip_message=None,
    )
    return state


# ---------------------------------------------------------------------------
# Executor / service mocks
# ---------------------------------------------------------------------------


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
def mock_executor(tasks_config, fresh_state) -> MagicMock:
    """
    Mock TaskExecutor with a two-task config and fresh state.

    Used by service-layer tests that should never touch the filesystem.
    """
    executor = MagicMock()
    executor.config_loader.load_tasks.return_value = tasks_config
    executor.state = fresh_state
    return executor


# ---------------------------------------------------------------------------
# Environment setup
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_archcare_user(monkeypatch):
    """
    Ensure ARCHCARE_USER is never set during tests.

    _update_state's chown block requires both is_root() AND ARCHCARE_USER.
    Clearing the env var makes the condition unconditionally False regardless
    of whether tests run as root (e.g. in a Docker-based CI pipeline).
    """
    monkeypatch.delenv("ARCHCARE_USER", raising=False)
