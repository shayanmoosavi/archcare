"""Shared fixtures for the Archcare integration test suite."""

from pathlib import Path

import pytest

from archcare.config import AppSettings


@pytest.fixture(autouse=True)
def archcare_home(monkeypatch, tmp_path: Path) -> Path:
    """
    Redirects AppSettings.home_dir to tmp_path for every integration test.

    Nothing in this suite should ever touch the real home directory or
    depend on the test machine's own state - SUDO_USER is also cleared so
    home_dir resolves via tmp_path/user rather than guessing a real path.
    """
    monkeypatch.delenv("SUDO_USER", raising=False)
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
