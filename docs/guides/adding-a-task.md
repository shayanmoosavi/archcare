# Adding a New Task

**Audience:** a contributor adding a maintenance task to the registry. This guide assumes you have
read the [Architecture Overview](../architecture/index.md) and the
[Task Execution Lifecycle](../architecture/task-lifecycle.md#the-basetask-contract) pages — the hook
contract is described once there and only summarized here.

By the end you will have implemented, wired, tested, and run a complete — if minimal — maintenance
task end to end. The worked example, `my-task`, counts error-level journal entries for the current
boot and writes them to a report file. It is deliberately tiny, but it exercises **every**
[`BaseTask`][archcare.core.base_task.BaseTask] hook, so the same skeleton scales to real tasks like
`journal-cleanup` or `orphan-removal` unchanged.

## Task or CLI command?

Add a **task** when the operation is scheduled or repeatable maintenance: idempotent, safe to run
unattended from a systemd timer, and productive of structured, typed output
([`TaskResult`][archcare.core.models.TaskResult] details) that a presenter can render. Add a **CLI
command** for one-shot operator actions that fit neither criterion (`setup`, `logs`, `debug`). If
you want it scheduled by a timer, or you need to answer "what changed since the last run", it's a
task.

## What you'll create

| #   | File                                        | You add                                                            | Layer  |
| --- | ------------------------------------------- | ------------------------------------------------------------------ | ------ |
| 1   | `src/archcare/core/task_details.py`         | `MyTaskDetails` frozen dataclass                                   | core   |
| 2   | `src/archcare/tasks/my_task.py`             | `MyTask` ([`BaseTask`][archcare.core.base_task.BaseTask] subclass) | tasks  |
| 3   | `src/archcare/tasks/__init__.py`            | `MyTask` export                                                    | tasks  |
| 4   | `src/archcare/core/__init__.py`             | `MyTaskDetails` export                                             | core   |
| 5   | `src/archcare/cli/presenters/formatters.py` | `MyTaskFormatter`                                                  | cli    |
| 6   | `src/archcare/cli/presenters/__init__.py`   | `MyTaskFormatter` export                                           | cli    |
| 7   | `src/archcare/cli/context.py`               | `TaskDescriptor("my-task", MyTask, MyTaskFormatter)`               | cli    |
| 8   | `src/archcare/config/defaults.py`           | `TaskConfig` row in `_AUTOMATIC_TASKS` or `_MANUAL_TASKS`          | config |
| 9   | `tests/unit/tasks/test_my_task.py`          | unit tests                                                         | tests  |
| 10  | `tests/integration/tasks/test_my_task.py`   | integration tests                                                  | tests  |

Rows 1–2 are the task itself; rows 3–8 are wiring; rows 9–10 keep it honest. Three of the wiring
edits are plain re-exports — easy to forget, and each omission fails somewhere confusing (see
[Pitfalls](#pitfalls)).

## Step 1 — the details dataclass

A task's [`TaskResult`][archcare.core.models.TaskResult] is generic over a per-task details
dataclass: this is the structured payload your formatter (for CLI or GUI) renders. Follow the
existing entries in [`archcare.core.task_details`][] — a frozen dataclass with defaults, a
Google-style docstring with an `Attributes:` section — and add one bullet to the module docstring's
task list.

```python title="src/archcare/core/task_details.py"
@dataclass(frozen=True)
class MyTaskDetails:
    """
    Details produced by [`MyTask.execute`][archcare.tasks.my_task.MyTask.execute].

    Attributes:
        entries (int): Number of error-level journal entries found this boot.
        sample (tuple[str, ...]): Up to 10 raw entry lines, for quick context.
    """

    entries: int = 0
    sample: tuple[str, ...] = ()
```

## Step 2 — the task class

[`BaseTask`][archcare.core.base_task.BaseTask] is a plain `ABC` built on the Template Method
pattern: its [`run()`][archcare.core.base_task.BaseTask.run] method owns the pipeline (logging
setup, gating, timing, teardown) and calls your hooks. Subclass it, implement
[`execute()`][archcare.core.base_task.BaseTask.execute], and override the rest only as needed. Note
that `BaseTask` itself takes **no** type parameter — the genericity lives in
`TaskResult[MyTaskDetails]` and the result factories.

```python title="src/archcare/tasks/my_task.py" linenums="1"
"""Skeleton task for the "Adding a New Task" guide: journal error digest."""

from pathlib import Path

from loguru import logger

from archcare.config import AppSettings, TaskConfig, TaskStatus
from archcare.config.enums import SkipReason
from archcare.core import TaskResult, TaskStep, failed, success
from archcare.core.base_task import BaseTask
from archcare.core.notifications import NotificationManager
from archcare.core.progress import TaskProgress
from archcare.core.task_details import MyTaskDetails
from archcare.utils.system import check_command_exists, run_command


class MyTask(BaseTask):
    """
    Count error-level journal entries since the current boot and save a report.

    Deliberately minimal teaching example: every
    [`BaseTask`][archcare.core.base_task.BaseTask] hook is exercised, and the only
    OS boundary is `archcare.utils.system`.
    """

    def __init__(
        self,
        config: TaskConfig,
        settings: AppSettings,
        notification_manager: NotificationManager | None = None,
        progress: TaskProgress | None = None,
    ) -> None:
        super().__init__(config, settings, notification_manager, progress)
        # Task-specific state goes in the subclass __init__, after super().__init__().
        self.report_path = self.settings.report_dir / "my-task-report.txt"

    def pre_check(self) -> tuple[bool, str]:
        """Hard prerequisite: without journalctl there is nothing to query."""
        if not check_command_exists("journalctl"):
            return False, "journalctl command not found (systemd not available)"
        return True, ""

    def should_run(self) -> tuple[bool, str, SkipReason | None]:
        """Skip cleanly when the journal has nothing to report this boot."""
        result = run_command(["journalctl", "-p", "err", "-b", "--no-pager", "-q"])
        if not result.success:
            # Can't probe - run anyway and let execute() report the failure properly.
            return True, "", None
        if not result.stdout.strip():
            return False, "No error-level journal entries this boot", SkipReason.NO_WORK_NEEDED
        return True, "", None

    def execute(self) -> TaskResult[MyTaskDetails]:
        """Collect the entries, persist a report, and return typed details."""
        logger.info("Collecting error-level journal entries")
        self.report_progress(TaskStep(name="Querying journal", status=TaskStatus.SUCCESS))

        result = run_command(["journalctl", "-p", "err", "-b", "--no-pager", "-q"])
        if not result.success:
            return failed(
                "journalctl query failed",
                error=f"exit code {result.returncode}: {result.stderr.strip()}",
                details=MyTaskDetails(),
            )

        # Clean up the output: Filter out empty strings/whitespace
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        self.report_path.write_text("\n".join(lines))

        details = MyTaskDetails(entries=len(lines), sample=tuple(lines[:10]))
        logger.info(f"Found {details.entries} error-level journal entries")
        return success(
            f"Found {details.entries} error-level journal entries",
            details=details,
        )

    def post_execute(self, result: TaskResult[MyTaskDetails]) -> None:
        """Runs after execute() whenever it *returns* - success or failure alike."""
        if result.is_failed() and self.notification_manager:
            self.notification_manager.send_task_result_notification(
                task_name=self.name,
                success=False,
                message=result.message,
            )

    def rollback(self) -> None:
        """Runs only when execute() raises an uncaught exception."""
        self.report_path.unlink(missing_ok=True)
```

What each hook contributes — the deep contract, including the exact skip plumbing inside `run()`,
is in the [lifecycle page](../architecture/task-lifecycle.md#the-basetask-contract):

| Hook           | When it runs                                                                          | What the example does                                                                                                                                  |
| -------------- | ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `__init__`     | when the [`TaskExecutor`][archcare.core.executor.TaskExecutor] instantiates the class | forwards config/settings via `super().__init__()`, then adds task state (`report_path`)                                                                |
| `pre_check`    | first gate                                                                            | env prerequisite via [`check_command_exists`][archcare.utils.system.check_command_exists]; `(False, reason)` skips with `SkipReason.DEPENDENCY_FAILED` |
| `should_run`   | second gate                                                                           | cheap probe; `(False, reason, skip_reason)` skips with that reason                                                                                     |
| `execute`      | the work, inside a contextualized logger                                              | the only required hook; returns `TaskResult[MyTaskDetails]`                                                                                            |
| `post_execute` | after `execute()` **returns** — success _or_ failure                                  | failure notification via the injected [`NotificationManager`][archcare.core.notifications.NotificationManager]                                         |
| `rollback`     | only if `execute()` **raises**                                                        | deletes the partially-written report                                                                                                                   |

The example's `execute()` makes a distinction worth internalizing: _expected_ failures (the command
ran but exited non-zero) are returned via [`failed()`][archcare.core.models.failed] — no rollback,
the run simply fails. _Unexpected_ exceptions (a bug, an I/O error mid-write) propagate out of
`execute()`; `run()` catches them, calls [`rollback()`][archcare.core.base_task.BaseTask.rollback],
and records the failure. Don't raise for conditions you can classify, and don't return `failed(...)`
for conditions that leave state behind.

## Step 3 — the formatter

Formatters live in `cli/presenters/formatters.py` and implement the
[`TaskDetailFormatter`][archcare.core.formatter.TaskDetailFormatter] port: a single
`format(details) -> list[str]` method returning Rich-markup lines, appended to the result panel by
the presenter in `--verbose` mode. Keep the markup conventions of the existing formatters (colored
count lines, a bold section header, truncated raw lines).

```python title="src/archcare/cli/presenters/formatters.py"
from archcare.core import MyTaskDetails


class MyTaskFormatter:
    """
    Formats details for the `my-task` task.

    See also:
        - [`FailedServicesTask`][archcare.tasks.failed_services.FailedServicesTask]:
            a production formatter for reference
    """

    def format(self, details: MyTaskDetails) -> list[str]:
        lines = [f"[blue]  Error-level entries: {details.entries}[/blue]"]
        if details.sample:
            lines.append("\n[bold]Sample:[/bold]")
            lines.extend(f"    {line[:160]}" for line in details.sample)
        return lines
```

Add `MyTaskDetails` to the `archcare.core` import block at the top of the module. If your details
need no custom rendering, you can skip this step entirely and let the registry fall back to the
[`DefaultFormatter`][archcare.core.formatter.DefaultFormatter] — but a typed formatter is
recommended for anything a user will read.

## Step 4 — wire the exports

Three one-line edits, all easy to forget:

```python title="src/archcare/tasks/__init__.py"
from .my_task import MyTask

__all__ = [
    # Existing tasks
    ...
    "MyTask",
]
```

```python title="src/archcare/core/__init__.py"
# add MyTaskDetails to the task_details re-export block, and one bullet to the
# module docstring's list of details payloads
```

```python title="src/archcare/cli/presenters/__init__.py"
from .formatters import (
    # Existing formatters
    ...
    MyTaskFormatter,
)
```

Each has a reason to exist: `cli/context.py` imports tasks and formatters **from the packages**, so
a missing `tasks/__init__.py` export breaks the registry import; unit tests import details classes
from `archcare.core`, so a missing core re-export breaks them; and the presenters package import is
what the registry constant references. In addition, it keeps the public API clean by avoiding deep
imports.

## Step 5 — register in the registry

Edit `DEFAULT_TASK_REGISTRY` in [`archcare.cli.context`][] — the single static
[`TaskRegistry`][archcare.core.task_registry.TaskRegistry] mapping each name to its class and CLI
formatter. Add it to the end of the tuple, like so:

```python title="src/archcare/cli/context.py"
DEFAULT_TASK_REGISTRY = TaskRegistry(
    (
        # Existing task descriptors
        ...,
        # New task descriptor
        TaskDescriptor("my-task", MyTask, MyTaskFormatter),
    )
)
```

The descriptor name must match the config key exactly — the registry and the config are two lists
that must agree before a task can run at all (see
[the registry page](../architecture/registry-and-ports.md#the-registry) for the two distinct
failure modes when they don't).

## Step 6 — add the default config row

[`archcare.config.defaults`][] builds the initial `tasks.toml` from two tuples of
[`TaskConfig`][archcare.config.models.TaskConfig] objects — `_AUTOMATED_TASKS` (run
unattended via systemd timers) and `_MANUAL_TASKS` (run on demand). Add your row to the appropriate
one that makes the most sense for your task; the raw TOML table is generated, never hand-written:

```python title="src/archcare/config/defaults.py"
# For demonstration, assumed to be manual
_MANUAL_TASKS = (
    # Existing task configurations
    ...,
    TaskConfig(
        name="my-task",
        type=TaskType.MANUAL,
        frequency=7,  # Whatever schedule that makes sense, weekly is a reasonable default
        description="Count error-level journal entries since boot",
        enabled=True,
    ),
)
```

!!! warning "Existing installs won't see the new task"

    The defaults only seed a **fresh** config (`archcare setup config`). A machine that already
    has `~/.config/archcare/tasks.toml` must get the `[my-task]` table added by hand — the
    generated table is exactly the five fields shown above.
    ```toml title="tasks.toml"
    [my-task]
    name = "my-task"
    type = "manual"
    frequency = 7
    description = "Count error-level journal entries since boot"
    enabled = true
    ```

## Step 7 — test it

Unit tests mock at the OS boundary only and exercise the hooks in isolation
(`tests/unit/tasks/test_my_task.py`). For the deliberately thin example task they
mostly pin the hook contract — read the note below before writing more.

??? note "Unit tests earn their keep only when they isolate real logic"

    The five tests below demonstrate the mocking boundary and pin the hook
    contract — but notice how little logic the example task owns, and how many
    assertions merely restate what the implementation visibly does. That is the
    smell to watch for: a unit test that duplicates the task's logic adds no new
    coverage and breaks for free whenever the implementation changes shape.
    Prefer covering task-specific behavior through the integration tests, and
    reserve unit tests for genuine logic worth testing in isolation — parsing,
    branching, categorization, formatting. `tests/unit/tasks/test_maintenance_check.py`
    is the in-repo reference: `MaintenanceCheckTask` owns issue categorization
    and formatting logic complex enough to justify unit-level coverage, while
    its end-to-end behavior still lives in the integration suite.

```python title="tests/unit/tasks/test_my_task.py" linenums="1"
"""
Unit tests for MyTask

Scope: hook behavior in isolation - pre_check gating, should_run skipping,
execute's result construction, rollback cleanup. The OS boundary
(run_command / check_command_exists) is the only thing mocked.
"""

from pathlib import Path

import pytest

from archcare.config import AppSettings, TaskConfig
from archcare.config.enums import SkipReason, TaskType
from archcare.tasks import MyTask
from archcare.utils.system import CommandResult

_MODULE = "archcare.tasks.my_task"


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _cmd_result(stdout: str = "", success: bool = True) -> CommandResult:
    return CommandResult(
        command="",
        returncode=0 if success else 1,
        stdout=stdout,
        stderr="",
        success=success,
    )


def _task(tmp_path: Path) -> MyTask:
    task = MyTask(
        config=TaskConfig(
            name="my-task",
            type=TaskType.MANUAL,
            frequency=7,
            description="Example task for the docs guide",
            enabled=True,
        ),
        settings=AppSettings(user="test"),
    )
    task.report_path = tmp_path / "my-task-report.txt"
    return task


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMyTask:
    def test_pre_check_fails_without_journalctl(self, mocker, tmp_path):
        mocker.patch(f"{_MODULE}.check_command_exists", return_value=False)
        can_run, reason = _task(tmp_path).pre_check()
        assert not can_run
        assert "journalctl" in reason

    def test_should_run_skips_when_journal_is_clean(self, mocker, tmp_path):
        mocker.patch(f"{_MODULE}.run_command", return_value=_cmd_result(""))
        should_run, reason, skip_reason = _task(tmp_path).should_run()
        assert not should_run
        assert skip_reason is SkipReason.NO_WORK_NEEDED

    def test_execute_reports_entries(self, mocker, tmp_path):
        mocker.patch(
            f"{_MODULE}.run_command",
            return_value=_cmd_result("error one\nerror two\n"),
        )
        result = _task(tmp_path).execute()
        assert result.is_success()
        assert result.details.entries == 2
        assert result.details.sample == ("error one", "error two")
        assert (tmp_path / "my-task-report.txt").exists()

    def test_execute_fails_when_query_fails(self, mocker, tmp_path):
        mocker.patch(f"{_MODULE}.run_command", return_value=_cmd_result(success=False))
        result = _task(tmp_path).execute()
        assert result.is_failed()

    def test_rollback_removes_partial_report(self, tmp_path):
        task = _task(tmp_path)
        task.report_path.write_text("partial")
        task.rollback()
        assert not task.report_path.exists()
```

```bash
uv run pytest tests/unit/tasks/test_my_task.py -q
# expected: 5 passed
```

Integration tests run the real CLI and real config I/O, mocking only the subprocess boundary
(`tests/integration/tasks/test_my_task.py`). This is where task-specific behavior belongs — assert
on pipeline outcomes (rendered output, `state.json` contents) rather than mirroring the
implementation line by line:

```python title="tests/integration/tasks/test_my_task.py" linenums="1"
"""Integration tests for my-task."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from archcare.cli.app import app
from archcare.utils.system import CommandResult

runner = CliRunner()

_MODULE = "archcare.tasks.my_task"
_SYSTEM_MODULE = "archcare.utils.system"


def _cmd_result(stdout: str = "", success: bool = True) -> CommandResult:
    return CommandResult(
        command="",
        returncode=0 if success else 1,
        stdout=stdout,
        stderr="",
        success=success,
    )


@pytest.fixture(autouse=True)
def mock_check_command_exists(mocker):
    return mocker.patch(f"{_MODULE}.check_command_exists", return_value=True)


@pytest.fixture(autouse=True)
def mock_run_command(mocker):
    return mocker.patch(
        f"{_SYSTEM_MODULE}.run_command",
        return_value=_cmd_result("nginx.service failed to start\n"),
    )


class TestMyTask:
    def test_reports_journal_errors_verbose(self, archcare_home: Path):
        runner.invoke(app, ["setup", "config"])

        result = runner.invoke(app, ["task", "run", "my-task", "--verbose"])

        assert result.exit_code == 0
        assert "Error-level entries: 1" in result.output
        assert "nginx.service failed to start" in result.output

    def test_skips_when_no_errors(self, archcare_home: Path, mock_run_command):
        mock_run_command.return_value = _cmd_result("")
        runner.invoke(app, ["setup", "config"])

        result = runner.invoke(app, ["task", "run", "my-task"])

        state = (archcare_home / ".local/state/archcare/state.json").read_text()
        assert result.exit_code == 0  # a skip is still a "successful" run
        assert '"last_status": "skipped"' in state
        assert '"skip_reason": "no_work_needed"' in state

    def test_pre_check_failure_records_dependency_failed(
        self, archcare_home: Path, mock_check_command_exists
    ):
        mock_check_command_exists.return_value = False
        runner.invoke(app, ["setup", "config"])

        result = runner.invoke(app, ["task", "run", "my-task"])

        state = (archcare_home / ".local/state/archcare/state.json").read_text()
        assert result.exit_code == 0
        assert '"skip_reason": "dependency_failed"' in state
```

```bash
uv run pytest tests/integration/tasks/test_my_task.py -q
# expected: 3 passed
```

## Step 8 — smoke-test on the CLI

```bash
uv run archcare task list
# expected: a row for "my-task"
uv run archcare task run my-task --force --verbose
# expected: SUCCESS, plus the formatter's "Error-level entries" block
```

`--force` bypasses the not-yet-due check from the scheduler; drop it once the task has been run
within its `frequency` window.

## Pitfalls

- **Never import from `cli/` or `services/` in `core/`, `tasks/`, or `config/`.** This is the
  project's one hard layering rule (see the [Architecture Overview](../architecture/index.md)).
  The task's OS boundary is [`archcare.utils.system`][archcare.utils.system] —
  [`run_command`][archcare.utils.system.run_command] /
  [`run_command_with_sudo`][archcare.utils.system.run_command_with_sudo] — nothing else.
- **Don't parameterize `BaseTask`.** It is a plain `ABC`; annotate
  `execute() -> TaskResult[MyTaskDetails]` instead. The type parameter belongs to
  [`TaskResult`][archcare.core.models.TaskResult] and the factories.
- **`pre_check` is for environment prerequisites; `should_run` is for work decisions.** A missing
  binary is `pre_check` (`DEPENDENCY_FAILED`); "nothing to do" is `should_run` (`NO_WORK_NEEDED`).
  They are classified differently downstream.
- **`rollback()` fires only on an uncaught exception**, never on a returned `failed(...)`.
  Conversely, `post_execute()` fires only when `execute()` _returns_ — an exception skips it and
  goes straight to `rollback()`.
- **Forgot an export?** A missing `tasks/__init__.py` export fails the registry import at startup;
  a missing `core/__init__.py` re-export fails unit tests with an `ImportError`; a missing
  presenters export fails `cli/context.py`.
- **The descriptor name, the `tasks.toml` key, and the CLI argument are one string** — keep them
  identical. A mismatch surfaces as
  [`TaskNotRegisteredError`][archcare.core.exceptions.TaskNotRegisteredError] or an unknown-task
  error depending on which side is missing.
- **If your task needs sudo**, say so in the class docstring, use
  [`run_command_with_sudo`][archcare.utils.system.run_command_with_sudo], pause progress rendering
  around the prompt (the health-check task wraps its sudo call in `self.progress.pause()`), and
  gate `pre_check` on the binary existing.

## Related pages

- [Task Execution Lifecycle](../architecture/task-lifecycle.md) — the `run()` pipeline your hooks
  plug into, and how state is persisted after every outcome.
- [Registry, Ports & Extensibility](../architecture/registry-and-ports.md) — the registry mechanics
  behind Step 5 and the port your formatter implements.
- [Configuration & state](../architecture/configuration.md) — how the `TaskConfig` row from Step 6
  is validated and where `state.json` records your task's runs.
- [Configuration files reference](../reference/configuration-files.md) — every `tasks.toml` key,
  with types and defaults.
