"""Unit tests for the CLI AppContext."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from archcare.cli.context import _TASK_REGISTRY, AppContext
from archcare.cli.interaction import CliInteraction
from archcare.config import AppSettings, LogLevel
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
    """
    Redirect AppSettings.home_dir to a fixed tmp_path, ignoring both `user`
    and SUDO_USER.

    Used wherever the exact user-resolution mechanism isn't under test
    (settings/executor caching, register_task wiring, init-gate presence
    checks). For tests that exercise the SUDO_USER indirection itself, see
    `per_user_home_dir` below instead.
    """
    monkeypatch.delenv("SUDO_USER", raising=False)
    home_dir = tmp_path / "home/testuser"
    monkeypatch.setattr(AppSettings, "home_dir", property(lambda _: home_dir))
    return home_dir


@pytest.fixture
def config_dir(mock_home: Path) -> Path:
    d = mock_home / ".config/archcare"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture(autouse=True)
def tasks_toml(config_dir: Path) -> Path:
    """Presence of this file is what setup_logging() gates on."""
    f = config_dir / "tasks.toml"
    f.touch()
    return f


@pytest.fixture
def mock_setup_logging(mocker) -> MagicMock:
    """Patches the setup_logging() function (not AppContext's method)."""
    return mocker.patch("archcare.cli.context.setup_logging")


@pytest.fixture
def mock_config_loader(mocker) -> MagicMock:
    """Patches ConfigLoader at its import site in context.py."""
    instance = MagicMock()
    mocker.patch("archcare.cli.context.ConfigLoader", MagicMock(return_value=instance))
    return instance


# ---------------------------------------------------------------------------
# is_interactive
# ---------------------------------------------------------------------------


class TestIsInteractive:
    def test_true_when_user_is_none(self, context: AppContext):
        assert context.is_interactive is True

    def test_false_when_user_is_set(self):
        context = AppContext(devel=False, user="alice")
        assert context.is_interactive is False


# ---------------------------------------------------------------------------
# settings property
# ---------------------------------------------------------------------------


class TestSettingsProperty:
    def test_loads_settings_via_loader(
        self, mock_config_loader: MagicMock, context: AppContext
    ):
        mock_config_loader.load_settings.return_value = "SETTINGS"

        assert context.settings == "SETTINGS"

    def test_caches_after_first_access(
        self, mock_config_loader: MagicMock, context: AppContext
    ):
        # Access settings twice
        first = context.settings
        second = context.settings

        # Ensure it was only loaded once
        assert first is second
        mock_config_loader.load_settings.assert_called_once()


# ---------------------------------------------------------------------------
# executor property
# ---------------------------------------------------------------------------


class TestExecutorProperty:
    def test_returns_built_executor(self, context: AppContext, mocker):
        executor_instance = MagicMock()
        mocker.patch(
            "archcare.cli.context.TaskExecutor",
            MagicMock(return_value=executor_instance),
        )

        assert context.executor is executor_instance

    def test_builds_with_loader_settings_and_state(
        self, mock_config_loader: MagicMock, mocker, context: AppContext
    ):
        mock_config_loader.load_settings.return_value = "SETTINGS"
        mock_config_loader.load_state.return_value = "STATE"

        mock_executor_class: MagicMock = mocker.patch(
            "archcare.cli.context.TaskExecutor"
        )

        context.executor

        _, kwargs = mock_executor_class.call_args
        assert kwargs["config_loader"] is mock_config_loader
        assert kwargs["settings"] == "SETTINGS"
        assert kwargs["state"] == "STATE"

    def test_builds_with_interactive_cli_interaction(self, mocker, context: AppContext):
        mock_executor_class: MagicMock = mocker.patch(
            "archcare.cli.context.TaskExecutor"
        )

        context.executor

        _, kwargs = mock_executor_class.call_args
        interaction = kwargs["interaction"]
        assert isinstance(interaction, CliInteraction)
        assert interaction.is_interactive is True

    def test_registers_all_known_tasks(self, mocker: MagicMock, context: AppContext):
        executor_instance = MagicMock()
        mocker.patch(
            "archcare.cli.context.TaskExecutor",
            MagicMock(return_value=executor_instance),
        )

        context.executor

        assert executor_instance.register_task.call_count == len(_TASK_REGISTRY)

    def test_executor_is_lazy_loaded_and_cached(self, mocker, context: AppContext):
        mock_executor_class: MagicMock = mocker.patch(
            "archcare.cli.context.TaskExecutor"
        )

        first = context.executor
        second = context.executor

        assert first is second
        mock_executor_class.assert_called_once()


# ---------------------------------------------------------------------------
# setup_logging
# ---------------------------------------------------------------------------


class TestSetupLogging:
    def test_raises_if_tasks_toml_missing(self, context: AppContext, tasks_toml: Path):
        # Ensure tasks.toml does NOT exist
        if tasks_toml.exists():
            tasks_toml.unlink()

        with pytest.raises(ConfigNotInitializedError):
            context.setup_logging()

    def test_succeeds_if_tasks_toml_exists(
        self, mock_setup_logging: MagicMock, context: AppContext
    ):

        # Should not raise
        context.setup_logging()

        # Verify the underlying utility was called
        assert mock_setup_logging.call_count >= 1

    def test_reconfigures_logging_if_settings_differ(
        self, mocker, mock_setup_logging: MagicMock, context: AppContext
    ):
        # Mock settings to differ from defaults
        mock_settings: AppSettings = mocker.patch.object(AppContext, "settings")
        mock_settings.log_level = LogLevel.DEBUG  # Different from default INFO

        context.setup_logging()

        # Should be called once for defaults, and a second time for reconfiguration
        assert mock_setup_logging.call_count == 2
        mock_setup_logging.assert_called_with(
            mock_settings, reconfigure=True, devel_mode=False
        )


# ---------------------------------------------------------------------------
# executor_for_user
# ---------------------------------------------------------------------------


class TestExecutorForUser:
    @patch("archcare.cli.context.TaskExecutor")
    def test_returns_new_uncached_executor(
        self, mock_executor_class, context: AppContext
    ):
        # Instruct the mock to return a brand new MagicMock on every instantiation
        mock_executor_class.side_effect = lambda **_: MagicMock()

        # Generate a targeted executor
        target_executor = context.executor_for_user("alice")

        # Instantiate the standard context executor
        cached_executor = context.executor

        # They should be distinct instances (TaskExecutor should have been constructed multiple times)
        assert target_executor is not cached_executor
        assert mock_executor_class.call_count == 2
