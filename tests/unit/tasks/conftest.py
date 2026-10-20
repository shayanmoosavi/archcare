"""Shared fixtures for tasks-layer unit tests."""

from collections.abc import Callable, Generator
from contextlib import contextmanager

import pytest

from archcare.core import TaskStep
from archcare.utils.system import CommandResult

# ---------------------------------------------------------------------------
# Behavioral sudo guard (shared across tasks)
# ---------------------------------------------------------------------------
#
# Invariant: every subprocess call that runs through `sudo` must never open a password
# prompt while a Rich live render — bar or *spinner* alike — is actually active. A
# `pause()` bracket is only ever needed *inside* a live render: calls made before any
# display is started (or after it stopped) reach the terminal cleanly. Two safe shapes exist:
#
#   1. nothing is being rendered at call time — either the call runs inside a
#      `progress.pause()` bracket of a running render (system-update:
#      backup/pacman/paru/snapper/paccache and the rollback restore; health-check:
#      `pacman -Qk`) or the run hasn't started (or already stopped) any display yet, or
#   2. the credentials were pre-warmed earlier in the same run by `sudo -v` executed while
#      nothing was rendered (mirrorlist-update, which deliberately keeps the reflector
#      spinner for its nondeterministic network phase — see `ensure_sudo_credentials`).
#
# Source-inspection (grep/AST over the task file) cannot enforce this reliably: the sudo
# wrapper is referenced only *inside the utils modules* — the task file imports the friendly
# helpers, never the wrapper — so the guard is behavioral. There is exactly one launch seam
# to replace: `utils.system._launch` is an alias of the source tree's only `subprocess.run`,
# and both wrappers funnel into it from their real bodies (`run_command_with_sudo` via the
# in-module `run_command` delegation) — so callers' from-imported *copies* of either wrapper
# are covered without any module discovery. `core.notifications` is the only other copy
# holder; its launches arrive unprefixed and are answered canned, never really run.
# The fixture patches that single seam, records each sudo-prefixed launch together with
# whether a display render was live at that moment, and answers everything else from
# `canned_stdout`. Contract: sudo-capable launches must funnel through `_launch`; if that
# ever breaks, the ledger goes vacuous and each task's anti-vacuous `first_tokens()`
# assertion fails loudly.

# argv shapes that refresh the sudo timestamp instead of performing work.
_CREDENTIAL_REFRESH_ARGUMENTS = (("-v",), ("sudo", "-v"))


class SudoPauseLedger:
    """Ledger shared by the sudo recorders and the progress double for one guarded run."""

    def __init__(self) -> None:
        self.display_live = False
        # `(argv, was_live)` for every recorded sudo-bound call, in call order.
        self.sudo_calls: list[tuple[tuple[str, ...], bool]] = []
        # Canned stdout for read-only commands, keyed on `(argv[0], argv[1])`.
        self.canned_stdout: dict[tuple[str, str], str] = {}
        # Side effects per first argv token (e.g. emulating reflector's file write), so
        # real helpers that *consume* the recorder's nominal output still work.
        self.side_effects: dict[str, Callable[[tuple[str, ...]], None]] = {}

    def unprotected_sudo_calls(self) -> list[tuple[tuple[str, ...], bool]]:
        """
        Return sudo calls that could have prompted against a live display.

        The full-invariant check: a call is safe when nothing was rendered at that moment
        (a `pause()` bracket of a running render, or the run hadn't started — or had already
        stopped — any display), or when a credential refresh was observed earlier in the run
        (the `sudo -v` timestamp covers subsequent non-interactive launches, even under the
        live reflector spinner). An unpaused `sudo -v` executed *while* a render is live is
        itself a violation: its prompt would be exactly the one swallowed.
        """
        hits: list[tuple[tuple[str, ...], bool]] = []
        warmed = False
        for argv, was_live in self.sudo_calls:
            if argv in _CREDENTIAL_REFRESH_ARGUMENTS:
                if was_live:
                    hits.append((argv, was_live))
                else:
                    warmed = True
            elif was_live and not warmed:
                hits.append((argv, was_live))
        return hits

    def first_tokens(self) -> set[str]:
        """Effective command token of every recorded sudo call (the vacuousness-control helper).

        Recorded argv is sudo-prefixed — `("sudo", "cp", ...)` — so the token right after
        it identifies the helper that launched the call.
        """
        return {self._effective_token(argv) for argv, _ in self.sudo_calls}

    @staticmethod
    def _effective_token(argv: tuple[str, ...]) -> str:
        """Command token after the wrapper's `sudo` prefix (`"cp"` for `("sudo", "cp", ...)`)."""
        if argv[:1] == ("sudo",) and len(argv) > 1:
            return argv[1]
        return argv[0] if argv else ""


class PauseAwareProgress:
    """
    A real `TaskProgress` that keeps the ledger truthful.

    A `MagicMock` would decouple the display lifecycle from what the recorders see, so the
    port is implemented for real: `start()` and `spinner()` turn the ledger's `display_live`
    on, `stop()` — and the spinner teardown — turn it off, and a `pause()` bracket stops the
    display for its duration. Mirror the real wrapper's quirk: `RichProgress.pause()` calls
    `start()` unconditionally on exit, so even a pause taken while nothing was ever rendered
    re-flags the display as live afterwards.
    """

    def __init__(self, ledger: SudoPauseLedger) -> None:
        self._ledger = ledger

    def start(self, total: int | None = None) -> None:
        self._ledger.display_live = True

    def advance(self, step: TaskStep) -> None:
        """Nothing to render in tests."""

    def stop(self) -> None:
        self._ledger.display_live = False

    @contextmanager
    def pause(self) -> Generator[None]:
        self._ledger.display_live = False
        try:
            yield
        finally:
            self._ledger.display_live = True

    @contextmanager
    def spinner(self, label: str) -> Generator[None]:
        self._ledger.display_live = True
        try:
            yield
        finally:
            self._ledger.display_live = False


@pytest.fixture
def sudo_pause_ledger(mocker) -> SudoPauseLedger:
    """Install the shared sudo-guard at the single launch seam.

    `archcare.utils.system._launch` aliases the source tree's only `subprocess.run`, and both
    wrappers funnel into it from their real bodies — so every caller's from-imported copy of
    either wrapper lands here and one patch covers the whole codebase, no discovery walk.
    The router records every sudo-prefixed launch (the wrapper already prepended `sudo`; a
    root run arrives unprefixed and is naturally plain traffic), applies registered
    `side_effects` to the caller-issued argv (sudo prefix stripped), and answers
    everything else from `canned_stdout`. The real utils helpers above the seam stay real.
    """
    ledger = SudoPauseLedger()

    def _recording_router(command, options=None, **kwargs):
        # The real run_command body calls _launch with exploded kwargs (capture_output,
        # text, check, timeout, cwd, env) — restated options are absorbed, not re-applied.
        argv = tuple(command) if not isinstance(command, str) else tuple(command.split())
        if argv and argv[0] == "sudo":
            # A sudo-prefixed launch can open a password prompt → record it verbatim.
            ledger.sudo_calls.append((argv, ledger.display_live))
        tail = argv[1:] if argv[:1] == ("sudo",) else argv
        side_effect = ledger.side_effects.get(tail[0]) if tail else None
        if side_effect is not None:
            side_effect(tail)
        probe = (tail[0], tail[1] if len(tail) > 1 else "") if tail else ("", "")
        return CommandResult(
            command="mock",
            returncode=0,
            stdout=ledger.canned_stdout.get(probe, ""),
            stderr="",
            success=True,
        )

    mocker.patch("archcare.utils.system._launch", new=_recording_router)
    return ledger
