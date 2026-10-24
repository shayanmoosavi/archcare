"""
Self-tests for the shared prompt guard (tests/unit/tasks/conftest.py).

The guard exists to fail loudly, so these tests prove the guard itself fails loudly: each
invariant branch raises `AssertionError` at the exact offending launch, the unwired guard
raises instead of silently certifying a display state nothing rendered, and deliberately
unguarded read-only traffic stays unguarded. All tests drive the REAL wrappers
(`run_command_with_sudo`, `ensure_sudo_credentials`, `run_command`) so the seam wiring is
exercised, not simulated.
"""

from collections.abc import Iterator

import pytest

from archcare.cli.progress import RichProgress
from archcare.utils.system import (
    CommandOptions,
    ensure_sudo_credentials,
    run_command,
    run_command_with_sudo,
)

from .conftest import PromptGuardLedger, bind_guard_progress

pytestmark = pytest.mark.usefixtures("no_task_logging")


@pytest.fixture
def bound_guard(
    prompt_guard_ledger: PromptGuardLedger,
) -> Iterator[tuple[PromptGuardLedger, RichProgress]]:
    """The standard guard wiring — ledger plus its bound real adapter.

    Mirrors how guard tests bind their adapter (the result of
    `bind_guard_progress(ledger)`, injected as `TaskDependencies(progress=...)`);
    teardown stops the render so no refresh thread outlives the test.
    """
    progress = bind_guard_progress(prompt_guard_ledger)
    yield prompt_guard_ledger, progress
    progress.stop()


class TestUnwiredGuard:
    @pytest.mark.usefixtures("prompt_guard_ledger")
    def test_first_guarded_launch_without_a_bound_progress_raises(self):
        """No bound progress means nothing ever rendered — certifying anything would be a lie."""
        with pytest.raises(AssertionError, match="prompt guard unwired"):
            run_command_with_sudo(["cp", "/src", "/dst"])


class TestSudoCredentialRefresh:
    def test_clean_refresh_warms_and_is_recorded(
        self, bound_guard: tuple[PromptGuardLedger, RichProgress]
    ):
        ledger, _progress = bound_guard

        assert ensure_sudo_credentials() is True

        assert ledger.warmed is True
        assert ledger.guarded_calls == [(("sudo", "-v"), False)]

    def test_refresh_while_the_render_is_live_raises(
        self, bound_guard: tuple[PromptGuardLedger, RichProgress]
    ):
        ledger, progress = bound_guard
        progress.start(total=2)

        with pytest.raises(AssertionError, match="credential refresh"):
            ensure_sudo_credentials()

        # The record is left behind before the raise (see observe_launch).
        assert ledger.guarded_calls[-1] == (("sudo", "-v"), True)


class TestSudoWork:
    def test_live_launch_without_a_warm_raises(
        self, bound_guard: tuple[PromptGuardLedger, RichProgress]
    ):
        ledger, progress = bound_guard
        progress.start(total=2)

        with pytest.raises(AssertionError, match="live display and no warm"):
            run_command_with_sudo(["cp", "/src", "/dst"])

        assert ledger.guarded_calls[-1] == (("sudo", "cp", "/src", "/dst"), True)

    def test_live_launch_after_a_clean_warm_passes(
        self, bound_guard: tuple[PromptGuardLedger, RichProgress]
    ):
        """The mirrorlist-update shape: pre-warmed `sudo -v`, reflector keeps its spinner."""
        ledger, progress = bound_guard
        assert ensure_sudo_credentials() is True
        progress.start(total=2)

        result = run_command_with_sudo(["reflector", "--save", "/tmp/mirrorlist"])

        assert result.success
        assert ledger.guarded_calls[-1] == (
            ("sudo", "reflector", "--save", "/tmp/mirrorlist"),
            True,
        )

    def test_launch_inside_a_pause_bracket_passes_cold(
        self, bound_guard: tuple[PromptGuardLedger, RichProgress]
    ):
        """The health-check shape: no warm, but the call sits inside `progress.pause()`."""
        ledger, progress = bound_guard
        progress.start(total=2)

        with progress.pause():
            result = run_command_with_sudo(["pacman", "-Qk"])

        assert result.success
        assert ledger.guarded_calls[-1] == (("sudo", "pacman", "-Qk"), False)


class TestParuSuaIsPromptCapable:
    def test_live_launch_raises_even_after_a_clean_warm(
        self, bound_guard: tuple[PromptGuardLedger, RichProgress]
    ):
        """
        No warm exemption: a fresh sudo timestamp covers credential prompts, not paru's
        own diff/build review prompts.
        """
        ledger, progress = bound_guard
        assert ensure_sudo_credentials() is True
        progress.start(total=2)

        with pytest.raises(AssertionError, match="prompt-capable"):
            run_command(["paru", "-Sua"], options=CommandOptions(capture_output=False))

        assert ledger.guarded_calls[-1][0] == ("paru", "-Sua")

    def test_launch_inside_a_pause_bracket_passes(
        self, bound_guard: tuple[PromptGuardLedger, RichProgress]
    ):
        ledger, progress = bound_guard
        progress.start(total=2)

        with progress.pause():
            result = run_command(["paru", "-Sua"], options=CommandOptions(capture_output=False))

        assert result.success
        assert ledger.guarded_calls[-1] == (("paru", "-Sua"), False)

    def test_launch_with_no_display_at_all_passes(
        self, bound_guard: tuple[PromptGuardLedger, RichProgress]
    ):
        """Shape 2: before any display started, a pause bracket is not needed."""
        ledger, _ = bound_guard

        result = run_command(["paru", "-Sua"], options=CommandOptions(capture_output=False))

        assert result.success
        assert ledger.guarded_calls[-1] == (("paru", "-Sua"), False)


class TestReadOnlyTrafficIsNotGuarded:
    def test_paru_qua_under_a_live_spinner_is_allowed_and_unrecorded(
        self, bound_guard: tuple[PromptGuardLedger, RichProgress]
    ):
        """
        Deliberate: system_update.py queries AUR updates under its live spinner — the
        query consumes no input, so `("paru", "-Qua")` is not in the prompt-capable table
        and must neither raise nor pollute the recorded guarded traffic.
        """
        ledger, progress = bound_guard

        with progress.spinner("Checking for AUR updates"):
            result = run_command(["paru", "-Qua"])

        assert result.success
        assert ledger.guarded_calls == []


class TestSwallowedViolationsStillFailTeardown:
    def test_a_swallowed_raise_leaves_a_recorded_violation(
        self, bound_guard: tuple[PromptGuardLedger, RichProgress]
    ):
        """
        Models `post_execute()`/`rollback()`'s deliberate `except Exception`: the raise
        disappears at the call, but the record is what fixture teardown re-asserts, so a
        swallowed violation can never pass silently.
        """
        ledger, progress = bound_guard
        progress.start(total=2)
        swallowed: AssertionError | None = None

        try:
            run_command_with_sudo(["cp", "/src", "/dst"])
        except AssertionError as e:
            swallowed = e  # the swallow under test — production logs and continues here.

        assert isinstance(swallowed, AssertionError)
        assert "live display and no warm" in ledger.violations[0]
