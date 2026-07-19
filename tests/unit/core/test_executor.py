"""Unit tests for TaskExecutor."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from archcare.config import (
    AppSettings,
    AppState,
    ConfigLoader,
    SkipReason,
    TaskConfig,
    TasksConfig,
)
from archcare.core import TaskDescriptor, TaskRegistry, TaskResult, success
from archcare.core.executor import TaskExecutor
from archcare.tasks import BaseTask
from archcare.utils import UserContext
from archcare.utils.notifications import NotificationManager

_MODULE = "archcare.core.executor"

pytestmark = pytest.mark.usefixtures("no_task_logging")

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
# Fixtures and Helpers
# ---------------------------------------------------------------------------

_EMPTY_REGISTRY = TaskRegistry(())  # for tests that don't care which tasks exist


@pytest.fixture
def tasks_config_with_disabled(
    automated_task: TaskConfig, disabled_task: TaskConfig
) -> TasksConfig:
    """Config containing both an enabled and a disabled task."""
    return TasksConfig(
        tasks={
            automated_task.name: automated_task,
            disabled_task.name: disabled_task,
        }
    )


@pytest.fixture
def mock_manager_class(mocker) -> MagicMock:
    return mocker.patch(f"{_MODULE}.NotificationManager")


def _make_executor(
    tasks_config: TasksConfig,
    state: AppState,
    interaction: RecordingInteraction,
    user: str | None = None,
    notification_manager: MagicMock | None = None,
    user_context: MagicMock | None = None,
) -> TaskExecutor:
    """
    Build a real TaskExecutor backed by a mock ConfigLoader.

    FakeTask is registered for every task present in tasks_config so
    the executor can instantiate tasks without hitting real task code.
    Command names are derived from the config itself, so fixture renames
    never cause silent mismatches here.

    notification_manager defaults to a MagicMock() - _create_task() now
    passes it to every task unconditionally, and without a default here
    the lazy property would construct a real NotificationManager() (and
    its real notify-send subprocess check) on every execute_task() call
    in this file.
    """
    loader = MagicMock(spec=ConfigLoader)
    loader.load_tasks.return_value = tasks_config
    loader.save_state = MagicMock()  # suppress filesystem writes

    task_registry = TaskRegistry(
        tuple(
            TaskDescriptor(name=task_config.name, task_class=FakeTask)
            for task_config in tasks_config.tasks.values()
        )
    )

    return TaskExecutor(
        config_loader=loader,
        settings=AppSettings(user=user),
        state=state,
        task_registry=task_registry,
        interaction=interaction,
        notification_manager=notification_manager
        or MagicMock(spec=NotificationManager),
        user_context=user_context or MagicMock(spec=UserContext),
    )


# ---------------------------------------------------------------------------
# notification_manager lazy property
# ---------------------------------------------------------------------------


class TestNotificationManagerProperty:
    """
    Mirrors AppContext's settings/executor laziness and BaseTask's own
    interaction-defaulting pattern - NotificationManager() does a real
    subprocess check, so it must not run until actually needed.
    """

    def test_returns_injected_instance(self, mock_manager_class: MagicMock):
        executor = TaskExecutor(
            config_loader=MagicMock(spec=ConfigLoader),
            settings=AppSettings(),
            state=AppState(),
            task_registry=_EMPTY_REGISTRY,
            notification_manager=mock_manager_class.return_value,
        )

        assert executor.notification_manager is mock_manager_class.return_value

    def test_not_constructed_until_first_access(self, mock_manager_class: MagicMock):

        TaskExecutor(
            config_loader=MagicMock(spec=ConfigLoader),
            settings=AppSettings(),
            state=AppState(),
            task_registry=_EMPTY_REGISTRY,
        )

        mock_manager_class.assert_not_called()

    def test_lazily_constructs_when_not_injected(self, mock_manager_class: MagicMock):
        mock_manager: MagicMock = mock_manager_class.return_value
        executor = TaskExecutor(
            config_loader=MagicMock(spec=ConfigLoader),
            settings=AppSettings(),
            state=AppState(),
            task_registry=_EMPTY_REGISTRY,
        )

        result = executor.notification_manager

        mock_manager_class.assert_called_once()
        assert result is mock_manager

    def test_lazy_construction_is_cached(self, mock_manager_class: MagicMock):
        executor = TaskExecutor(
            config_loader=MagicMock(spec=ConfigLoader),
            settings=AppSettings(),
            state=AppState(),
            task_registry=_EMPTY_REGISTRY,
        )

        first = executor.notification_manager
        second = executor.notification_manager

        assert first is second
        mock_manager_class.assert_called_once()


# ---------------------------------------------------------------------------
# user_context construction
# ---------------------------------------------------------------------------


class TestUserContextConstruction:
    def test_uses_injected_user_context(self):
        mock_user_context = MagicMock(spec=UserContext)
        executor = TaskExecutor(
            config_loader=MagicMock(spec=ConfigLoader),
            settings=AppSettings(),
            state=AppState(),
            task_registry=_EMPTY_REGISTRY,
            user_context=mock_user_context,
        )

        assert executor.user_context is mock_user_context

    def test_defaults_to_user_context_from_env(self, mocker):
        mock_user_context_class: MagicMock = mocker.patch(f"{_MODULE}.UserContext")

        executor = TaskExecutor(
            config_loader=MagicMock(spec=ConfigLoader),
            settings=AppSettings(),
            state=AppState(),
            task_registry=_EMPTY_REGISTRY,
        )

        mock_user_context_class.from_env.assert_called_once()
        assert executor.user_context is mock_user_context_class.from_env.return_value


# ---------------------------------------------------------------------------
# _create_task threads notification_manager down to every task
# ---------------------------------------------------------------------------


class TestCreateTask:
    def test_task_receives_notification_manager(
        self,
        tasks_config: TasksConfig,
        fresh_state: AppState,
        automated_task: TaskConfig,
        mock_manager_class: MagicMock,
    ):
        interaction = RecordingInteraction()
        mock_manager = mock_manager_class.return_value
        executor = _make_executor(
            tasks_config, fresh_state, interaction, notification_manager=mock_manager
        )

        task_config = tasks_config.get_task(automated_task.name)
        task = executor._create_task(task_config)

        assert task.notification_manager is mock_manager


# ---------------------------------------------------------------------------
# Disabled-task branch
# ---------------------------------------------------------------------------


class TestHandleDisabledTask:
    """_handle_disabled_task is exercised when enabled=False in the config."""

    def test_notify_called_when_task_is_disabled(
        self,
        tasks_config_with_disabled: TasksConfig,
        fresh_state: AppState,
        disabled_task: TaskConfig,
    ):
        interaction = RecordingInteraction(confirm_response=False)
        executor = _make_executor(tasks_config_with_disabled, fresh_state, interaction)

        executor.execute_task(disabled_task.name)

        assert len(interaction.notifications) > 0
        assert any("disabled" in msg.lower() for msg, _ in interaction.notifications)

    def test_confirm_called_exactly_once_in_interactive_mode(
        self,
        tasks_config_with_disabled: TasksConfig,
        fresh_state: AppState,
        disabled_task: TaskConfig,
    ):
        interaction = RecordingInteraction(confirm_response=False)
        executor = _make_executor(tasks_config_with_disabled, fresh_state, interaction)

        executor.execute_task(disabled_task.name)

        assert len(interaction.confirmations) == 1

    def test_user_declined_returns_user_cancelled(
        self,
        tasks_config_with_disabled: TasksConfig,
        fresh_state: AppState,
        disabled_task: TaskConfig,
    ):
        interaction = RecordingInteraction(confirm_response=False)
        executor = _make_executor(tasks_config_with_disabled, fresh_state, interaction)

        result = executor.execute_task(disabled_task.name)

        assert result.is_skipped()
        assert result.skip_reason == SkipReason.USER_CANCELLED

    def test_user_confirmed_task_actually_executes(
        self,
        tasks_config_with_disabled: TasksConfig,
        fresh_state: AppState,
        disabled_task: TaskConfig,
    ):
        interaction = RecordingInteraction(confirm_response=True)
        executor = _make_executor(tasks_config_with_disabled, fresh_state, interaction)

        result = executor.execute_task(disabled_task.name)

        assert result.is_success()

    def test_systemd_mode_skips_without_prompting(
        self,
        tasks_config_with_disabled: TasksConfig,
        fresh_state: AppState,
        disabled_task: TaskConfig,
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
        self,
        tasks_config: TasksConfig,
        state_with_recent_run: AppState,
        automated_task: TaskConfig,
    ):
        interaction = RecordingInteraction(confirm_response=False)
        executor = _make_executor(tasks_config, state_with_recent_run, interaction)

        executor.execute_task(automated_task.name)

        assert len(interaction.notifications) > 0
        assert any("not due" in msg.lower() for msg, _ in interaction.notifications)

    def test_user_declined_returns_user_cancelled(
        self,
        tasks_config: TasksConfig,
        state_with_recent_run: AppState,
        automated_task: TaskConfig,
    ):
        interaction = RecordingInteraction(confirm_response=False)
        executor = _make_executor(tasks_config, state_with_recent_run, interaction)

        result = executor.execute_task(automated_task.name)

        assert result.is_skipped()
        assert result.skip_reason == SkipReason.USER_CANCELLED

    def test_user_confirmed_task_actually_executes(
        self,
        tasks_config: TasksConfig,
        state_with_recent_run: AppState,
        automated_task: TaskConfig,
    ):
        interaction = RecordingInteraction(confirm_response=True)
        executor = _make_executor(tasks_config, state_with_recent_run, interaction)

        result = executor.execute_task(automated_task.name)

        assert result.is_success()

    def test_systemd_mode_skips_without_prompting(
        self,
        tasks_config: TasksConfig,
        state_with_recent_run: AppState,
        automated_task: TaskConfig,
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
        self,
        tasks_config_with_disabled: TasksConfig,
        fresh_state: AppState,
        disabled_task: TaskConfig,
    ):
        interaction = RecordingInteraction(confirm_response=False)
        executor = _make_executor(tasks_config_with_disabled, fresh_state, interaction)

        result = executor.execute_task(disabled_task.name, force=True)

        assert result.is_success()
        assert len(interaction.confirmations) == 0

    def test_force_runs_not_due_task_without_prompting(
        self,
        tasks_config: TasksConfig,
        state_with_recent_run: AppState,
        automated_task: TaskConfig,
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
        self,
        tasks_config: TasksConfig,
        fresh_state: AppState,
        automated_task: TaskConfig,
    ):
        interaction = RecordingInteraction()
        executor = _make_executor(tasks_config, fresh_state, interaction)

        executor.execute_task(automated_task.name)

        executor.config_loader.save_state.assert_called_once()  # pyright: ignore[reportAttributeAccessIssue]  # ty:ignore[unresolved-attribute]

    def test_save_state_called_even_when_skipped(
        self,
        tasks_config: TasksConfig,
        state_with_recent_run: AppState,
        automated_task: TaskConfig,
    ):
        """State must be persisted for skipped tasks so the scheduler stays
        in sync — verifies the update path runs regardless of outcome."""
        interaction = RecordingInteraction(confirm_response=False)
        executor = _make_executor(tasks_config, state_with_recent_run, interaction)

        executor.execute_task(automated_task.name)

        executor.config_loader.save_state.assert_called_once()  # pyright: ignore[reportAttributeAccessIssue]  # ty:ignore[unresolved-attribute]

    # -- next_due calculation ------------------------------------------------

    def test_successful_run_sets_next_due_in_future(
        self,
        tasks_config: TasksConfig,
        fresh_state: AppState,
        automated_task: TaskConfig,
    ):
        interaction = RecordingInteraction()
        executor = _make_executor(tasks_config, fresh_state, interaction)

        executor.execute_task(automated_task.name)

        task_state = fresh_state.get_task_state(automated_task.name)
        assert task_state.next_due is not None
        assert task_state.next_due > datetime.now()

    def test_successful_next_due_respects_task_frequency(
        self,
        tasks_config: TasksConfig,
        fresh_state: AppState,
        automated_task: TaskConfig,
    ):
        interaction = RecordingInteraction()
        executor = _make_executor(tasks_config, fresh_state, interaction)

        before = datetime.now()
        executor.execute_task(automated_task.name)
        after = datetime.now()

        task_state = fresh_state.get_task_state(automated_task.name)
        expected_min = before + timedelta(days=automated_task.frequency)
        expected_max = after + timedelta(days=automated_task.frequency)
        assert expected_min <= task_state.next_due <= expected_max  # ty:ignore[unsupported-operator]

    def test_skipped_not_due_preserves_existing_next_due(
        self,
        tasks_config: TasksConfig,
        state_with_recent_run: AppState,
        automated_task: TaskConfig,
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
        self,
        tasks_config_with_disabled: TasksConfig,
        fresh_state: AppState,
        disabled_task: TaskConfig,
    ):
        """Disabled tasks have no schedule, so next_due should be None."""
        interaction = RecordingInteraction(confirm_response=False)
        executor = _make_executor(tasks_config_with_disabled, fresh_state, interaction)
        executor.execute_task(disabled_task.name)

        task_state = fresh_state.get_task_state(disabled_task.name)
        assert task_state.next_due is None

    # -- chown delegation ----------------------------------------------------

    def test_chown_if_root_called_with_state_file_and_parent(
        self,
        tasks_config: TasksConfig,
        fresh_state: AppState,
        automated_task: TaskConfig,
    ):
        mock_user_context = MagicMock(spec=UserContext)
        interaction = RecordingInteraction()
        executor = _make_executor(
            tasks_config, fresh_state, interaction, user_context=mock_user_context
        )

        executor.execute_task(automated_task.name)

        state_file = executor.settings.state_file
        mock_user_context.chown_if_root.assert_called_once_with(
            state_file, state_file.parent
        )
