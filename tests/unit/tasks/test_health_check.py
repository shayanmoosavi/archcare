"""
Unit tests for HealthCheckTask (tasks/health_check.py).

Seeded by the sudo-guard work: this task's only sudo-bound helper is `check_package_files`
(`sudo pacman -Qk`, wrapped in `progress.pause()` inside `execute()`). Everything else is
either psutil-backed or answered from the shared ledger's canned stdout, so the guard runs
the real orchestration and certifies the pause bracket.
"""

from pathlib import Path

import pytest
from _pytest.monkeypatch import MonkeyPatch

from archcare.config import AppSettings, TaskConfig
from archcare.tasks.health_check import HealthCheckTask
from archcare.utils.info_models import CpuInfo, DiskUsageInfo, MemoryInfo

from .conftest import PauseAwareProgress, SudoPauseLedger

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
    tmp_path: Path, monkeypatch: MonkeyPatch, health_check_config: TaskConfig
) -> HealthCheckTask:
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    return HealthCheckTask(config=health_check_config, settings=AppSettings(user=None))


@pytest.fixture
def sudo_guard(
    sudo_pause_ledger: SudoPauseLedger, mocker, task: HealthCheckTask
) -> SudoPauseLedger:
    """
    Health-check wiring for the shared guard.

    Non-sudo check helpers (psutil-backed and journal-backed) are stubbed at the task module
    so the run is deterministic on any machine; the sudo helper (`check_package_files` →
    `pacman -Qk`) stays REAL, powered by canned stdout, because its pause bracket is exactly
    what the shared ledger certifies — except for its pacman-availability gate, which is
    stubbed so the launch is not skipped on CI images without pacman.
    """
    ledger = sudo_pause_ledger
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

    task.progress = PauseAwareProgress(ledger)
    return ledger


class TestEverySudoCallRunsWhilePaused:
    """The task owns exactly one sudo call (`pacman -Qk`); the guard pins that it ran paused."""

    def test_execute_pauses_around_the_pacman_qk_call(
        self, task: HealthCheckTask, sudo_guard: SudoPauseLedger
    ):
        task.execute()

        assert sudo_guard.unprotected_sudo_calls() == []
        # Recorded argv is sudo-prefixed: ("sudo", "pacman", "-Qk", ...).
        qk_calls = [call for call in sudo_guard.sudo_calls if call[0][1:3] == ("pacman", "-Qk")]
        assert len(qk_calls) == 1, f"expected exactly one pacman -Qk launch, got {qk_calls}"
        assert not qk_calls[0][1], (
            "pacman -Qk must execute while the display is not live (inside its pause bracket)"
        )

    def test_the_guard_observes_the_documented_sudo_helper(
        self, task: HealthCheckTask, sudo_guard: SudoPauseLedger
    ):
        """Negative control against an accidental vacuous pass of the assertion above."""
        task.execute()

        assert sudo_guard.sudo_calls, "recorder captured no sudo traffic; harness is vacuous"
        assert sudo_guard.first_tokens() == {"pacman"}
