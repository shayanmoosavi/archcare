"""Unit tests for TaskExecutor."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

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
# Not-due branch
# ---------------------------------------------------------------------------


class TestHandleNotDueTask:
    """_handle_due_task is exercised when the task has a future next_due."""

    def test_notify_called_when_task_is_not_due(
        self, tasks_config, state_with_recent_run, automated_task
    ):
        interaction = RecordingInteraction(confirm_response=False)
        executor = _make_executor(tasks_config, state_with_recent_run, interaction)

        executor.execute_task(automated_task.name)

        assert len(interaction.notifications) > 0
        assert any("not due" in msg.lower() for msg, _ in interaction.notifications)

    def test_user_declined_returns_user_cancelled(
        self, tasks_config, state_with_recent_run, automated_task
    ):
        interaction = RecordingInteraction(confirm_response=False)
        executor = _make_executor(tasks_config, state_with_recent_run, interaction)

        result = executor.execute_task(automated_task.name)

        assert result.is_skipped()
        assert result.skip_reason == SkipReason.USER_CANCELLED

    def test_user_confirmed_task_actually_executes(
        self, tasks_config, state_with_recent_run, automated_task
    ):
        interaction = RecordingInteraction(confirm_response=True)
        executor = _make_executor(tasks_config, state_with_recent_run, interaction)

        result = executor.execute_task(automated_task.name)

        assert result.is_success()

    def test_systemd_mode_skips_without_prompting(
        self, tasks_config, state_with_recent_run, automated_task
    ):
        interaction = RecordingInteraction(confirm_response=True)
        executor = _make_executor(
            tasks_config, state_with_recent_run, interaction, user="alice"
        )

        result = executor.execute_task(automated_task.name)

        assert len(interaction.confirmations) == 0
        assert result.is_skipped()
        assert result.skip_reason == SkipReason.NOT_DUE


# ---------------------------------------------------------------------------
# Force flag
# ---------------------------------------------------------------------------


class TestForceFlag:
    """force=True bypasses both the disabled check and the due check."""

    def test_force_runs_disabled_task_without_prompting(
        self, tasks_config_with_disabled, fresh_state, disabled_task
    ):
        interaction = RecordingInteraction(confirm_response=False)
        executor = _make_executor(tasks_config_with_disabled, fresh_state, interaction)

        result = executor.execute_task(disabled_task.name, force=True)

        assert result.is_success()
        assert len(interaction.confirmations) == 0

    def test_force_runs_not_due_task_without_prompting(
        self, tasks_config, state_with_recent_run, automated_task
    ):
        interaction = RecordingInteraction(confirm_response=False)
        executor = _make_executor(tasks_config, state_with_recent_run, interaction)

        result = executor.execute_task(automated_task.name, force=True)

        assert result.is_success()
        assert len(interaction.confirmations) == 0


# ---------------------------------------------------------------------------
# _update_state
# ---------------------------------------------------------------------------


class TestUpdateState:
    """
    _update_state is called at the end of every execute_task() path.
    Tests verify save_state, next_due calculation, and the chown guard.
    """

    # -- save_state ----------------------------------------------------------

    def test_save_state_called_after_successful_run(
        self, tasks_config, fresh_state, automated_task
    ):
        interaction = RecordingInteraction()
        executor = _make_executor(tasks_config, fresh_state, interaction)

        executor.execute_task(automated_task.name)

        executor.config_loader.save_state.assert_called_once()

    def test_save_state_called_even_when_skipped(
        self, tasks_config, state_with_recent_run, automated_task
    ):
        """State must be persisted for skipped tasks so the scheduler stays
        in sync — verifies the update path runs regardless of outcome."""
        interaction = RecordingInteraction(confirm_response=False)
        executor = _make_executor(tasks_config, state_with_recent_run, interaction)

        executor.execute_task(automated_task.name)

        executor.config_loader.save_state.assert_called_once()

    # -- next_due calculation ------------------------------------------------

    def test_successful_run_sets_next_due_in_future(
        self, tasks_config, fresh_state, automated_task
    ):
        interaction = RecordingInteraction()
        executor = _make_executor(tasks_config, fresh_state, interaction)

        executor.execute_task(automated_task.name)

        task_state = fresh_state.get_task_state(automated_task.name)
        assert task_state.next_due is not None
        assert task_state.next_due > datetime.now()

    def test_successful_next_due_respects_task_frequency(
        self, tasks_config, fresh_state, automated_task
    ):
        interaction = RecordingInteraction()
        executor = _make_executor(tasks_config, fresh_state, interaction)

        before = datetime.now()
        executor.execute_task(automated_task.name)
        after = datetime.now()

        task_state = fresh_state.get_task_state(automated_task.name)
        expected_min = before + timedelta(days=automated_task.frequency)
        expected_max = after + timedelta(days=automated_task.frequency)
        assert expected_min <= task_state.next_due <= expected_max

    def test_skipped_not_due_preserves_existing_next_due(
        self, tasks_config, state_with_recent_run, automated_task
    ):
        """NOT_DUE skip must not overwrite the previously calculated next_due."""
        original_next_due = state_with_recent_run.get_task_state(
            automated_task.name
        ).next_due

        interaction = RecordingInteraction(confirm_response=False)
        executor = _make_executor(tasks_config, state_with_recent_run, interaction)
        executor.execute_task(automated_task.name)

        task_state = state_with_recent_run.get_task_state(automated_task.name)
        assert task_state.next_due == original_next_due

    def test_disabled_skip_sets_next_due_to_none(
        self, tasks_config_with_disabled, fresh_state, disabled_task
    ):
        """Disabled tasks have no schedule, so next_due should be None."""
        interaction = RecordingInteraction(confirm_response=False)
        executor = _make_executor(tasks_config_with_disabled, fresh_state, interaction)
        executor.execute_task(disabled_task.name)

        task_state = fresh_state.get_task_state(disabled_task.name)
        assert task_state.next_due is None

    # -- chown guard ---------------------------------------------------------

    def test_chown_not_called_when_not_root(
        self, tasks_config, fresh_state, automated_task, monkeypatch
    ):
        monkeypatch.setenv("ARCHCARE_USER", "alice")
        with patch("archcare.core.executor.change_ownership_to_user") as mock_chown:
            interaction = RecordingInteraction(confirm_response=True)
            executor = _make_executor(tasks_config, fresh_state, interaction)
            executor.execute_task(automated_task.name)
            mock_chown.assert_not_called()

    def test_chown_not_called_when_archcare_user_absent(
        self, tasks_config, fresh_state, automated_task
    ):
        """ARCHCARE_USER is cleared by the autouse clear_archcare_user fixture."""
        with (
            patch("archcare.core.executor.is_root", return_value=True),
            patch("archcare.core.executor.change_ownership_to_user") as mock_chown,
        ):
            interaction = RecordingInteraction()
            executor = _make_executor(tasks_config, fresh_state, interaction)
            executor.execute_task(automated_task.name)

        mock_chown.assert_not_called()

    def test_chown_called_for_state_file_and_parent_when_root_via_systemd(
        self, tasks_config, fresh_state, automated_task, monkeypatch
    ):

        monkeypatch.setenv("ARCHCARE_USER", "alice")

        with (
            patch("archcare.core.executor.is_root", return_value=True),
            patch("archcare.core.executor.change_ownership_to_user") as mock_chown,
        ):
            interaction = RecordingInteraction(confirm_response=True)
            executor = _make_executor(
                tasks_config, fresh_state, interaction, user="alice"
            )
            executor.execute_task(automated_task.name)

            # Systemd mode must have user set in AppSettings
            assert executor.settings.user == "alice"

            # After state update, check that chown was called twice (file and parent)
            assert mock_chown.call_count == 2
            state_file = executor.settings.state_file
            mock_chown.assert_any_call(state_file, "alice")
            mock_chown.assert_any_call(state_file.parent, "alice")


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
