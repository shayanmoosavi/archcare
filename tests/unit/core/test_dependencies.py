"""Unit tests for the TaskDependencies collaborator bundle."""

import dataclasses

import pytest

from archcare.core import TaskDependencies
from archcare.core.interaction import NonInteractive
from archcare.core.notifications import NotificationManager
from archcare.core.progress import NoOpProgress

# ---------------------------------------------------------------------------
# TaskDependencies
# ---------------------------------------------------------------------------


class TestTaskDependencies:
    def test_defaults(self):
        """
        Load-bearing beyond just data — `BaseTask` assigns deps.interaction/deps.progress
        directly, so omitted fields must materialize null objects, never None.
        notification_manager is the deliberate exception: None is its documented
        "no notifier supplied" state, resolved lazily at the executor.
        """
        deps = TaskDependencies()

        assert isinstance(deps.interaction, NonInteractive)
        assert isinstance(deps.progress, NoOpProgress)
        assert deps.notification_manager is None

    def test_custom_values(self, mocker):
        # Patching the real PATH probe so the test is environment independant
        mocker.patch("archcare.core.notifications.check_command_exists")

        interaction = NonInteractive()
        progress = NoOpProgress()
        notification_manager = NotificationManager()
        deps = TaskDependencies(
            interaction=interaction,
            progress=progress,
            notification_manager=notification_manager,
        )

        assert deps.interaction is interaction
        assert deps.progress is progress
        assert deps.notification_manager is notification_manager

    def test_omitted_fields_still_get_their_defaults(self):
        progress = NoOpProgress()
        deps = TaskDependencies(progress=progress)

        assert deps.progress is progress
        assert isinstance(deps.interaction, NonInteractive)
        assert deps.notification_manager is None

    def test_is_frozen(self):
        deps = TaskDependencies()

        with pytest.raises(dataclasses.FrozenInstanceError):
            deps.progress = NoOpProgress()  # ty:ignore[invalid-assignment]

    def test_default_ports_not_shared_across_instances(self):
        first = TaskDependencies()
        second = TaskDependencies()

        assert first.interaction is not second.interaction
        assert first.progress is not second.progress
