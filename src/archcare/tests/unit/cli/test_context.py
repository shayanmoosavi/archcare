"""Unit tests for the CLI AppContext."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from archcare.cli.context import AppContext
from archcare.config import AppSettings
from archcare.services.exceptions import ConfigNotInitializedError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def context() -> AppContext:
    """A standard interactive context (no user set)."""
    return AppContext(devel=False, user=None)


@pytest.fixture
def mock_home(monkeypatch, tmp_path) -> Path:
    """Isolate AppSettings paths to tmp_path."""
    monkeypatch.setattr(AppSettings, "home_dir", property(lambda _: tmp_path))
    return tmp_path


# ---------------------------------------------------------------------------
# Properties and Caching
# ---------------------------------------------------------------------------


class TestAppContextProperties:
    def test_is_interactive_true_when_user_is_none(self, context: AppContext):
        assert context.is_interactive is True

    def test_is_interactive_false_when_user_is_set(self):
        ctx = AppContext(devel=False, user="systemd-user")
        assert ctx.is_interactive is False

    @patch("archcare.cli.context.ConfigLoader")
    def test_settings_are_lazy_loaded_and_cached(
        self, mock_loader_class, context: AppContext
    ):
        # Setup mock loader instance
        mock_loader = MagicMock()
        mock_loader_class.return_value = mock_loader

        # Access settings twice
        first = context.settings
        second = context.settings

        # Ensure it was only loaded once
        assert first is second
        mock_loader.load_settings.assert_called_once()

    @patch("archcare.cli.context.TaskExecutor")
    def test_executor_is_lazy_loaded_and_cached(
        self, mock_executor_class, context: AppContext
    ):
        mock_executor_class.return_value = MagicMock()

        first = context.executor
        second = context.executor

        assert first is second
        mock_executor_class.assert_called_once()


# ---------------------------------------------------------------------------
# setup_logging
# ---------------------------------------------------------------------------


class TestSetupLogging:
    def test_raises_if_tasks_toml_missing(self, context, mock_home):
        # Ensure tasks.toml does NOT exist
        tasks_file = mock_home / ".config/archcare/tasks.toml"
        if tasks_file.exists():
            tasks_file.unlink()

        with pytest.raises(ConfigNotInitializedError):
            context.setup_logging()

    @patch("archcare.cli.context.setup_logging")
    def test_succeeds_if_tasks_toml_exists(
        self, mock_setup_logging_util, context, mock_home
    ):
        # Fake the initialization
        config_dir = mock_home / ".config/archcare"
        config_dir.mkdir(parents=True)
        (config_dir / "tasks.toml").touch()

        # Should not raise
        context.setup_logging()

        # Verify the underlying utility was called
        assert mock_setup_logging_util.call_count >= 1

    @patch("archcare.cli.context.setup_logging")
    def test_reconfigures_logging_if_settings_differ(
        self, mock_setup_logging_util, context, mock_home
    ):
        config_dir = mock_home / ".config/archcare"
        config_dir.mkdir(parents=True)
        (config_dir / "tasks.toml").touch()

        # Mock settings to differ from defaults
        with patch.object(
            AppContext, "settings", new_callable=MagicMock
        ) as mock_settings:
            mock_settings.log_level = "DEBUG"  # Different from default INFO
            context.setup_logging()

            # Should be called once for defaults, and a second time for reconfiguration
            assert mock_setup_logging_util.call_count == 2
            mock_setup_logging_util.assert_called_with(
                mock_settings, reconfigure=True, devel_mode=False
            )


# ---------------------------------------------------------------------------
# executor_for_user
# ---------------------------------------------------------------------------


class TestExecutorForUser:
    @patch("archcare.cli.context.TaskExecutor")
    def test_returns_new_uncached_executor(
        self, mock_executor_class, context, mock_home
    ):
        # Instruct the mock to return a brand new MagicMock on every instantiation
        mock_executor_class.side_effect = lambda **kwargs: MagicMock()

        # Satisfy setup_logging checks
        config_dir = mock_home / ".config/archcare"
        config_dir.mkdir(parents=True)
        (config_dir / "tasks.toml").touch()

        # Generate a targeted executor
        target_executor = context.executor_for_user("alice")

        # Instantiate the standard context executor
        cached_executor = context.executor

        # They should be distinct instances (TaskExecutor should have been constructed multiple times)
        assert target_executor is not cached_executor
        assert mock_executor_class.call_count == 2
