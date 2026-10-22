"""Shared fixtures and helpers for the Archcare integration test suite."""

import json
import re
from pathlib import Path
from typing import Any

import pytest
from _pytest.monkeypatch import MonkeyPatch

from archcare.config import AppSettings

# ANSI colour codes and Rich's box-drawing characters. Both are presentation
# details that would otherwise break substring assertions on captured output.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_BOX_RE = re.compile(r"[│┃╭╮╰╯┌┐└┘├┤┬┴┼─━]")


def clean_output(output: str) -> str:
    """
    Normalise terminal output for substring assertions.

    Rich renders result panels with a border and hard-wraps the message at the console width, so one
    sentence arrives split across several lines and framed by box-drawing characters. Stripping the
    ANSI codes and the border, then collapsing the remaining whitespace, turns the panel back into
    one continuous string.

    Args:
        output (str): Raw `CliRunner` output.

    Returns:
        str: The same text without styling, borders, or line breaks.
    """
    return re.sub(r"\s+", " ", _BOX_RE.sub(" ", _ANSI_RE.sub("", output))).strip()


def task_state(archcare_home: Path, task_name: str) -> dict[str, Any]:
    """
    Read one task's persisted state out of `state.json`.

    Args:
        archcare_home (Path): The redirected home directory of the test.
        task_name (str): Name of the task whose state is wanted.

    Returns:
        dict[str, Any]: The task's state entry, or an empty dict when the task
            has never been run.
    """
    path = archcare_home / ".local/state/archcare/state.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text()).get("tasks", {}).get(task_name, {})


@pytest.fixture(autouse=True)
def archcare_home(monkeypatch: MonkeyPatch, tmp_path: Path) -> Path:
    """
    Redirects AppSettings.home_dir to tmp_path for every integration test.

    Nothing in this suite should ever touch the real home directory or depend on the test machine's
    own state - `SUDO_USER` is also cleared so `home_dir` resolves via `tmp_path`/`user` rather than
    guessing a real path.

    `ARCHCARE_USER` is cleared for the same reason: it is what makes a run *headless*, and the
    headless path is a different code path entirely (no interactive ports, a muted console). A
    developer who exports it would silently get the headless behaviour everywhere, so the suite
    pins it unset and lets the headless tests set it deliberately.
    """
    monkeypatch.delenv("SUDO_USER", raising=False)
    monkeypatch.delenv("ARCHCARE_USER", raising=False)
    home = tmp_path / "home"
    monkeypatch.setattr(AppSettings, "home_dir", property(lambda _: home))
    return home


@pytest.fixture(autouse=True)
def mock_notification_manager(mocker):
    """
    NotificationManager.__init__() does a real notify-send availability
    check, and a real send would attempt an actual desktop notification -
    neither is something an integration test should ever do for real.
    """
    return mocker.patch("archcare.core.executor.NotificationManager")


@pytest.fixture(autouse=True)
def mock_progress(mocker):
    """
    RichProgress would otherwise try to render a live display during every
    task run - harmless functionally, but pollutes captured CliRunner
    output that every test in this suite does substring assertions
    against. Same reasoning as mock_notification_manager above.
    """
    return mocker.patch("archcare.cli.context.RichProgress")
