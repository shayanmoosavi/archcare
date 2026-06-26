"""Unit tests for TaskExecutor."""

from unittest.mock import MagicMock

import pytest

from archcare.config import (
    AppSettings,
    AppState,
    ConfigLoader,
    SkipReason,
    TasksConfig,
)
from archcare.core import TaskExecutor
from archcare.core.models import TaskResult, success
from archcare.tasks.base import BaseTask

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class RecordingInteraction:
    """
    Stub + spy implementation of the TaskInteraction port.

    confirm_response controls the return value of every confirm() call.
    notifications and confirmations record every call for assertion.
    """

    def __init__(self, confirm_response: bool = False) -> None:
        self.notifications: list[tuple[str, str]] = []
        self.confirmations: list[str] = []
        self._confirm_response = confirm_response

    def notify(self, message: str, level: str = "info") -> None:
        self.notifications.append((message, level))

    def confirm(self, prompt: str) -> bool:
        self.confirmations.append(prompt)
        return self._confirm_response


class FakeTask(BaseTask):
    """Minimal BaseTask that always succeeds — used to verify a task ran."""

    def execute(self) -> TaskResult:
        return success("FakeTask completed")


# ---------------------------------------------------------------------------
# Executor factory
# ---------------------------------------------------------------------------


def _make_executor(
    tasks_config: TasksConfig,
    state: AppState,
    interaction: RecordingInteraction,
    user: str | None = None,
) -> TaskExecutor:
    """
    Build a real TaskExecutor backed by a mock ConfigLoader.

    FakeTask is registered for every command present in tasks_config so
    the executor can instantiate tasks without hitting real task code.
    Command names are derived from the config itself, so fixture renames
    never cause silent mismatches here.
    """
    loader = MagicMock(spec=ConfigLoader)
    loader.load_tasks.return_value = tasks_config
    loader.save_state = MagicMock()  # suppress filesystem writes

    executor = TaskExecutor(
        config_loader=loader,
        settings=AppSettings(user=user),
        state=state,
        interaction=interaction,
    )

    for task_config in tasks_config.tasks.values():
        executor.register_task(task_config.command, FakeTask)

    return executor


# ---------------------------------------------------------------------------
# Disabled-task branch
# ---------------------------------------------------------------------------


class TestHandleDisabledTask:
    """_handle_disabled_task is exercised when enabled=False in the config."""

    def test_notify_called_when_task_is_disabled(
        self, tasks_config_with_disabled, fresh_state, disabled_task
    ):
        interaction = RecordingInteraction(confirm_response=False)
        executor = _make_executor(tasks_config_with_disabled, fresh_state, interaction)

        executor.execute_task(disabled_task.name)

        assert len(interaction.notifications) > 0
        assert any("disabled" in msg.lower() for msg, _ in interaction.notifications)

    def test_confirm_called_exactly_once_in_interactive_mode(
        self, tasks_config_with_disabled, fresh_state, disabled_task
    ):
        interaction = RecordingInteraction(confirm_response=False)
        executor = _make_executor(tasks_config_with_disabled, fresh_state, interaction)

        executor.execute_task(disabled_task.name)

        assert len(interaction.confirmations) == 1

    def test_user_declined_returns_user_cancelled(
        self, tasks_config_with_disabled, fresh_state, disabled_task
    ):
        interaction = RecordingInteraction(confirm_response=False)
        executor = _make_executor(tasks_config_with_disabled, fresh_state, interaction)

        result = executor.execute_task(disabled_task.name)

        assert result.is_skipped()
        assert result.skip_reason == SkipReason.USER_CANCELLED

    def test_user_confirmed_task_actually_executes(
        self, tasks_config_with_disabled, fresh_state, disabled_task
    ):
        interaction = RecordingInteraction(confirm_response=True)
        executor = _make_executor(tasks_config_with_disabled, fresh_state, interaction)

        result = executor.execute_task(disabled_task.name)

        assert result.is_success()

    def test_systemd_mode_skips_without_prompting(
        self, tasks_config_with_disabled, fresh_state, disabled_task
    ):
        """user=<name> signals systemd mode; no TTY, so no confirm prompt."""
        interaction = RecordingInteraction(confirm_response=True)
        executor = _make_executor(
            tasks_config_with_disabled, fresh_state, interaction, user="alice"
        )

        result = executor.execute_task(disabled_task.name)

        assert len(interaction.confirmations) == 0
        assert result.is_skipped()
        assert result.skip_reason == SkipReason.DISABLED


# ---------------------------------------------------------------------------
# Fixtures local to executor tests
# ---------------------------------------------------------------------------


@pytest.fixture
def tasks_config_with_disabled(automated_task, disabled_task) -> TasksConfig:
    """Config containing both an enabled and a disabled task."""
    return TasksConfig(
        tasks={
            automated_task.name: automated_task,
            disabled_task.name: disabled_task,
        }
    )
