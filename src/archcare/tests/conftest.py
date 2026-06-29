"""Shared fixtures for the Archcare test suite."""

from datetime import datetime, timedelta
from io import StringIO
from unittest.mock import MagicMock, Mock, patch

import pytest
from loguru import logger

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
def tasks_config(automated_task: TaskConfig, manual_task: TaskConfig) -> TasksConfig:
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
def state_with_recent_run(automated_task: TaskConfig) -> AppState:
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
def state_with_overdue_run(automated_task: TaskConfig) -> AppState:
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
def mock_executor(tasks_config: TasksConfig, fresh_state: AppState) -> MagicMock:
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


@pytest.fixture(autouse=True)
def no_task_logging():
    """
    Prevent BaseTask.run() from creating task log files during tests.

    setup_task_logging() is patched to add a loguru handler that writes to
    an in-memory buffer instead of a real file. This matters because loguru's
    logger.remove(handler_id) is called in BaseTask.run()'s finally block —
    returning a fake id would raise ValueError, so we return a real one.
    """
    with patch(
        "archcare.tasks.base.setup_task_logging",
        side_effect=lambda name, settings: logger.add(
            StringIO(), format="{message}", colorize=False
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def reset_notification_manager():
    """
    Reset the notification manager singleton between tests.

    NotificationManager.__init__ calls check_command_exists("notify-send"),
    a real subprocess check. Without this reset, the first test to trigger
    get_notification_manager() caches the result for the entire session,
    making tests environment-dependent.
    """
    import archcare.utils.notifications as notif_module

    notif_module._notification_manager = None
    yield
    notif_module._notification_manager = None
