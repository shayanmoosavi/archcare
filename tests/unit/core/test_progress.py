"""Unit tests for the core progress port and its NoOp default."""

from archcare.config import TaskStatus
from archcare.core import TaskStep
from archcare.core.progress import NoOpProgress


class TestNoOpProgress:
    """
    Confirms NoOpProgress is safe to call unconditionally - it's the
    default for every task, including ones that never touch self.progress
    at all (e.g. FailedServicesTask), so every method must be a true no-op.
    """

    def test_start_does_nothing(self):
        NoOpProgress().start(total=5)  # must not raise

    def test_start_accepts_none_total(self):
        NoOpProgress().start(total=None)  # must not raise

    def test_advance_does_nothing(self):
        step = TaskStep(name="x", status=TaskStatus.SUCCESS)
        NoOpProgress().advance(step)  # must not raise

    def test_stop_does_nothing(self):
        NoOpProgress().stop()  # must not raise

    def test_spinner_is_a_working_context_manager(self):
        body_ran = False
        with NoOpProgress().spinner("label"):
            body_ran = True
        assert body_ran

    def test_pause_is_a_working_context_manager(self):
        body_ran = False
        with NoOpProgress().pause():
            body_ran = True
        assert body_ran
