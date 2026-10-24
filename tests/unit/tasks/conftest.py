"""
Shared fixtures for tasks-layer unit tests.

Hosts the shared **prompt guard**: a fail-fast harness certifying that every launch able
to open a prompt — sudo traffic (including the `sudo -v` credential refresh) and the
non-sudo interactive tools in `_PROMPT_CAPABLE_TOOLS` — runs while no Rich live render
(bar or spinner) is active, so redrawing cannot swallow the prompt. A guarded launch is
safe inside a `progress.pause()` bracket, while no display is up, or — sudo only — under
a clean `sudo -v` pre-warm from earlier in the run; a fresh timestamp never exempts a
non-sudo prompt such as `paru`'s diff review.

The guard is behavioral rather than source-level: tasks import the friendly helpers and
never the wrapper itself, so the fixture patches the single launch seam —
`utils.system._launch`, the source tree's only `subprocess.run`, that both wrappers
funnel into — and raises `AssertionError` at the exact offending launch (argv, display
state, remedy). Liveness is read from the task's own `RichProgress.is_live`, injected
through `TaskDependencies(progress=...)` — the executor's real port contract, so the
wiring under test is the production wiring — and a guard with no bound progress raises
on its first guarded launch instead of "certifying" a display state nothing rendered.
If launches ever bypass the seam the recording goes vacuous, which each task's
anti-vacuous `first_tokens()` assertion flags loudly.
"""

from collections.abc import Callable
from io import StringIO

import pytest
from rich.console import Console

from archcare.cli.progress import RichProgress
from archcare.core import TaskDependencies
from archcare.utils.system import CommandOptions, CommandResult

# The only argv that refreshes the sudo timestamp instead of performing work.
_CREDENTIAL_REFRESH_ARGUMENTS = (("sudo", "-v"),)

# `(argv[0], argv[1])` pairs whose own prompts must never meet a live render — the
# extension point for future interactive commands. Read-only queries (paru -Qua, -Pw,
# informant, checkupdates) stay out and may run against a render.
_PROMPT_CAPABLE_TOOLS: frozenset[tuple[str, str]] = frozenset({("paru", "-Sua")})


class PromptGuardLedger:
    """Prompt-guard state for one run: recorded launches, warm credit, and canned answers."""

    def __init__(self) -> None:
        # Real adapter bound by `bind_guard_progress` and injected via TaskDependencies.
        self.progress: RichProgress | None = None
        # A clean `sudo -v` ran earlier in this run: sudo work may ride the display.
        self.warmed = False
        # `(argv, was_live)` per guarded launch, in order; sudo-bound argv keeps its prefix.
        self.guarded_calls: list[tuple[tuple[str, ...], bool]] = []
        # Violation messages, kept because tasks deliberately swallow `Exception`
        # (post_execute/rollback) — the guard fixtures re-assert this list at teardown.
        self.violations: list[str] = []
        # Canned stdout for read-only commands, keyed on `(argv[0], argv[1])`.
        self.canned_stdout: dict[tuple[str, str], str] = {}
        # Side effects per first argv token, so real helpers consuming nominal output work.
        self.side_effects: dict[str, Callable[[tuple[str, ...]], None]] = {}

    @property
    def display_live(self) -> bool:
        """
        Whether the bound adapter's render is live right now.

        `False` when the guard is unwired — `observe_launch` rejects unbound guarded
        launches before ever trusting this value.
        """
        if self.progress is None:
            return False
        return self.progress.is_live

    def observe_launch(self, argv: tuple[str, ...]) -> None:
        """
        Record one guarded launch and enforce the prompt invariant at it.

        Raises `AssertionError` naming the launch, display state, and remedy, in
        evaluation order:

        1. guard unwired (no progress bound) — recorded liveness would be a lie;
        2. credential refresh while live — its own prompt would be swallowed; a clean
           refresh arms `self.warmed` instead;
        3. sudo work while live with no warm timestamp — cold credentials would prompt
           against the render (a warm timestamp under a live render is legitimate);
        4. `_PROMPT_CAPABLE_TOOLS` launch while live — no warm exemption, because its
           review prompts are not credential prompts.

        Side Effects:
            Appends `(argv, was_live)` to `guarded_calls` — before raising, so a caught
            violation leaves its trace — records the message in `violations` for the
            teardown re-check, and updates `warmed`.
        """
        if self.progress is None:
            raise self._violation(
                f"prompt guard unwired: {list(argv)} is a guarded launch but no progress "
                "was bound — inject bind_guard_progress(ledger) through "
                "TaskDependencies(progress=...)"
            )
        was_live = self.display_live
        self.guarded_calls.append((argv, was_live))

        if argv in _CREDENTIAL_REFRESH_ARGUMENTS:
            if was_live:
                raise self._violation(
                    f"prompt guard violation: {list(argv)} ran while the display was "
                    "live — a credential refresh must happen before the display starts, "
                    "inside progress.pause(), or after it stops"
                )
            self.warmed = True
        elif argv[:1] == ("sudo",):
            if was_live and not self.warmed:
                raise self._violation(
                    f"prompt guard violation: {list(argv)} ran with a live display and "
                    "no warm sudo timestamp — wrap it in progress.pause() or pre-warm "
                    "with `sudo -v` while the display is down"
                )
        elif argv[:2] in _PROMPT_CAPABLE_TOOLS:
            if was_live:
                raise self._violation(
                    f"prompt guard violation: {list(argv)} is prompt-capable and ran "
                    "while the display was live (warm credentials do not exempt it) — "
                    "wrap it in progress.pause()"
                )

    def _violation(self, message: str) -> AssertionError:
        """
        Record a guard violation and return it for raising.

        The record is what fixture teardown re-asserts: `post_execute()`/`rollback()`
        deliberately swallow `Exception`, so an immediate raise alone could disappear
        and let a violating run pass silently.
        """
        self.violations.append(message)
        return AssertionError(message)

    def first_tokens(self) -> set[str]:
        """
        Effective command token of every recorded guarded launch (the vacuousness control).

        Sudo-bound argv is recorded prefixed (`("sudo", "cp", ...)` → `"cp"`), so the
        token after the prefix names the helper; prompt-capable argv is recorded as
        launched (`("paru", "-Sua")` → `"paru"`).
        """
        return {self._effective_token(argv) for argv, _ in self.guarded_calls}

    @staticmethod
    def _effective_token(argv: tuple[str, ...]) -> str:
        """Command token after the wrapper's `sudo` prefix (`"cp"` for `("sudo", "cp", ...)`)."""
        if argv[:1] == ("sudo",) and len(argv) > 1:
            return argv[1]
        return argv[0] if argv else ""


def bind_guard_progress(ledger: PromptGuardLedger) -> RichProgress:
    """
    Bind a real, headless `RichProgress` to the ledger and return it.

    Hand the result to the task as `TaskDependencies(progress=...)`: liveness must come
    from the object the task actually drives, or the ledger would certify a display that
    never existed.

    Args:
        ledger (PromptGuardLedger): Ledger that reads `is_live` off the adapter.

    Returns:
        RichProgress: The bound adapter, ready for `TaskDependencies(progress=...)`.
    """
    progress = RichProgress(console=Console(file=StringIO()))
    ledger.progress = progress
    return progress


@pytest.fixture
def task_deps() -> TaskDependencies:
    """
    Port bundle every task under test is constructed with — the shape the executor delivers.

    Guard tests override this fixture in their class to carry the guard's progress, so the
    task receives its port through `TaskDependencies` exactly as `TaskExecutor._create_task()`
    delivers it, instead of having `task.progress` assigned after construction.
    """
    return TaskDependencies()


@pytest.fixture
def prompt_guard_ledger(mocker) -> PromptGuardLedger:
    """
    Install the prompt guard at the single launch seam, pinned to a non-root runner.

    `archcare.utils.system._launch` is the source tree's only `subprocess.run`, and both
    wrappers funnel into it from their real bodies — one patch covers every caller's
    from-imported copy. `is_root` is pinned `False` for uniformity: as root the wrappers
    drop the `sudo` prefix and skip `sudo -v` entirely, so guarded launches would bypass
    the router and the guard would certify nothing. The router sends guarded launches
    (sudo-prefixed or in `_PROMPT_CAPABLE_TOOLS`) through the ledger's fail-fast check,
    applies registered `side_effects` to the prefix-stripped argv, and answers everything
    else from `canned_stdout`. The real helpers above the seam stay real — certifying
    them is the point.
    """
    ledger = PromptGuardLedger()

    def _prompt_guard_router(
        command: list[str] | str, options: CommandOptions | None = None, **kwargs
    ):
        # run_command explodes its options into kwargs here; absorbed, not re-applied.
        argv = tuple(command) if not isinstance(command, str) else tuple(command.split())
        if argv[:1] == ("sudo",) or argv[:2] in _PROMPT_CAPABLE_TOOLS:
            ledger.observe_launch(argv)
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

    mocker.patch("archcare.utils.system.is_root", return_value=False)
    mocker.patch("archcare.utils.system._launch", new=_prompt_guard_router)
    return ledger
