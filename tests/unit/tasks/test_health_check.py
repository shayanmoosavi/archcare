"""
Unit tests for HealthCheckTask (tasks/health_check.py).

Seeded by the prompt-guard work: this task's only sudo-bound helper is `check_package_files`
(`sudo pacman -Qk`, wrapped in `progress.pause()` inside `execute()`). Everything else is
either psutil-backed or answered from the shared ledger's canned stdout, so the guard runs
the real orchestration and certifies the pause bracket.
"""

from pathlib import Path

import pytest
from _pytest.monkeypatch import MonkeyPatch

from archcare.config import AppSettings, TaskConfig
from archcare.core import TaskDependencies
from archcare.tasks.health_check import HealthCheckTask
from archcare.utils.info_models import CpuInfo, DiskUsageInfo, MemoryInfo

from .conftest import PromptGuardLedger, bind_guard_progress

_MODULE = "archcare.tasks.health_check"
_PACMAN_MODULE = "archcare.utils.pacman"

pytestmark = pytest.mark.usefixtures("no_task_logging")


@pytest.fixture
def health_check_config() -> TaskConfig:
    return TaskConfig.model_validate(
        {
            "name": "health-check",
            "type": "manual",
            "frequency": 30,
            "description": "Perform health checks on system components",
            "enabled": True,
        }
    )


@pytest.fixture
def task(
    task_deps: TaskDependencies,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    health_check_config: TaskConfig,
) -> HealthCheckTask:
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    return HealthCheckTask(
        config=health_check_config, settings=AppSettings(user=None), deps=task_deps
    )


@pytest.fixture
def prompt_guard(prompt_guard_ledger: PromptGuardLedger, mocker) -> PromptGuardLedger:
    """
    Health-check wiring for the shared guard.

    Non-sudo check helpers (psutil-backed and journal-backed) are stubbed at the task module
    so the run is deterministic on any machine; the sudo helper (`check_package_files` →
    `pacman -Qk`) stays REAL, powered by canned stdout, because its pause bracket is exactly
    what the shared ledger certifies — except for its pacman-availability gate, which is
    stubbed so the launch is not skipped on CI images without pacman.
    """
    ledger = prompt_guard_ledger
    ledger.canned_stdout.update({("pacman", "-Qk"): "linux 5981 files, 0 missing files\n"})

    # `check_package_files`/`check_pacman_database` return early with "pacman command not
    # found" when `pacman` is absent from PATH — true on ubuntu-latest CI. Stub the
    # availability check at its launch-site module so the guard observes the `pacman -Qk`
    # launch deterministically on any machine.
    mocker.patch(f"{_PACMAN_MODULE}.check_command_exists", return_value=True)

    mocker.patch(f"{_MODULE}.get_disk_usage", return_value=DiskUsageInfo(percent=42.0))
    mocker.patch(
        f"{_MODULE}.get_memory_info",
        return_value=MemoryInfo(percent=37.0, available=8_000_000_000),
    )
    mocker.patch(
        f"{_MODULE}.get_cpu_info",
        return_value=CpuInfo(cores=4, percent=10.0, load_avg=(0.5, 0.5, 0.5)),
    )
    mocker.patch(f"{_MODULE}.get_system_uptime", return_value="1 day, 3:45")
    mocker.patch(f"{_MODULE}.check_filesystem_errors", return_value=[])

    return ledger


class TestEveryGuardedLaunchRunsWhilePaused:
    """
    The task's only guarded launch (`pacman -Qk`, sudo-bound) must run paused — a live
    launch would raise inside the fail-fast router at the call itself.
    """

    @pytest.fixture
    def task_deps(self, prompt_guard: PromptGuardLedger) -> TaskDependencies:
        """Class-scoped override: tasks under the guard receive progress via TaskDependencies."""
        return TaskDependencies(progress=bind_guard_progress(prompt_guard))

    def test_task_drives_the_guard_bound_adapter(
        self, task: HealthCheckTask, prompt_guard: PromptGuardLedger
    ):
        """The bundle must deliver the bound adapter itself — the guard reads `is_live` off it."""
        assert task.progress is prompt_guard.progress

    def test_execute_pauses_around_the_pacman_qk_call(
        self, task: HealthCheckTask, prompt_guard: PromptGuardLedger
    ):
        task.execute()

        # Recorded argv is sudo-prefixed: ("sudo", "pacman", "-Qk", ...).
        qk_calls = [
            (argv, was_live)
            for argv, was_live in prompt_guard.guarded_calls
            if argv[1:3] == ("pacman", "-Qk")
        ]
        assert len(qk_calls) == 1, f"expected exactly one pacman -Qk launch, got {qk_calls}"
        _, live = qk_calls[0]
        assert not live, (
            "pacman -Qk must execute while the display is not live (inside its pause bracket)"
        )

    def test_the_guard_observes_the_documented_sudo_helper(
        self, task: HealthCheckTask, prompt_guard: PromptGuardLedger
    ):
        """Negative control against an accidental vacuous pass of the assertion above."""
        task.execute()

        assert prompt_guard.guarded_calls, "recorder saw no guarded traffic; harness is vacuous"
        assert prompt_guard.first_tokens() == {"pacman"}
