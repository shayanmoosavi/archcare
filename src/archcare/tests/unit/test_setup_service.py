"""Unit tests for ConfigService and TimerService."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from archcare.services.setup_service import ConfigService, TimerService

_PATCH_CREATE_CONFIG = "archcare.services.setup_service.create_default_config_files"
_PATCH_SYSTEMCTL = "archcare.services.setup_service.run_systemctl"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _systemctl_result(success: bool, stdout: str = "") -> MagicMock:
    result = MagicMock()
    result.success = success
    result.stdout = stdout
    return result


# ---------------------------------------------------------------------------
# ConfigService
# ---------------------------------------------------------------------------


class TestConfigService:
    def test_default_config_dir_is_under_home(self):
        service = ConfigService()
        assert service.config_dir == Path.home() / ".config/archcare"

    def test_custom_config_dir_is_accepted(self, tmp_path):
        service = ConfigService(config_dir=tmp_path)
        assert service.config_dir == tmp_path

    def test_check_existing_returns_empty_when_dir_absent(self, tmp_path):
        service = ConfigService(config_dir=tmp_path / "nonexistent")
        assert service.check_existing() == []

    def test_check_existing_returns_empty_when_dir_has_no_toml(self, tmp_path):
        config_dir = tmp_path / "archcare"
        config_dir.mkdir()
        (config_dir / "readme.txt").touch()
        service = ConfigService(config_dir=config_dir)
        assert service.check_existing() == []

    def test_check_existing_finds_toml_files(self, tmp_path):
        config_dir = tmp_path / "archcare"
        config_dir.mkdir()
        (config_dir / "settings.toml").touch()
        (config_dir / "tasks.toml").touch()
        service = ConfigService(config_dir=config_dir)
        found = service.check_existing()
        assert len(found) == 2

    def test_check_existing_excludes_non_toml_files(self, tmp_path):
        config_dir = tmp_path / "archcare"
        config_dir.mkdir()
        (config_dir / "settings.toml").touch()
        (config_dir / "readme.txt").touch()
        service = ConfigService(config_dir=config_dir)
        found = service.check_existing()
        assert all(f.suffix == ".toml" for f in found)

    def test_initialize_returns_response_with_correct_config_dir(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(_PATCH_CREATE_CONFIG, lambda *a, **kw: None)
        result = ConfigService(config_dir=tmp_path).initialize()
        assert result.config_dir == tmp_path

    def test_initialize_calls_create_with_correct_dir(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(
            _PATCH_CREATE_CONFIG,
            lambda config_dir, **kw: calls.append(config_dir),
        )
        ConfigService(config_dir=tmp_path).initialize()
        assert calls[0] == tmp_path

    def test_initialize_always_passes_force_true(self, tmp_path, monkeypatch):
        """initialize() must overwrite existing files unconditionally."""
        calls = []
        monkeypatch.setattr(
            _PATCH_CREATE_CONFIG,
            lambda config_dir, force=False: calls.append(force),
        )
        ConfigService(config_dir=tmp_path).initialize()
        assert calls[0] is True
