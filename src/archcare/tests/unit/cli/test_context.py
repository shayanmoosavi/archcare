"""Unit tests for the CLI AppContext."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from archcare.cli.context import _TASK_REGISTRY, AppContext
from archcare.cli.interaction import CliInteraction
from archcare.config import AppSettings, LogLevel
from archcare.core import TaskExecutor
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


@pytest.fixture(autouse=True)
def mock_setup_logging(mocker) -> MagicMock:
    """Patches the setup_logging() function (not AppContext's method)."""
    return mocker.patch("archcare.cli.context.setup_logging")


@pytest.fixture
def mock_config_loader(mocker) -> MagicMock:
    """Patches ConfigLoader at its import site in context.py."""
    return mocker.patch("archcare.cli.context.ConfigLoader").return_value


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
        mock_executor: MagicMock = mocker.patch(
            "archcare.cli.context.TaskExecutor"
        ).return_value
        assert context.executor is mock_executor

    def test_builds_with_loader_settings_and_state(
        self, mock_config_loader: MagicMock, mocker, context: AppContext
    ):
        mock_config_loader.load_settings.return_value = "SETTINGS"
        mock_config_loader.load_state.return_value = "STATE"

        mock_executor: MagicMock = mocker.patch("archcare.cli.context.TaskExecutor")

        context.executor

        _, kwargs = mock_executor.call_args
        assert kwargs["config_loader"] is mock_config_loader
        assert kwargs["settings"] == "SETTINGS"
        assert kwargs["state"] == "STATE"

    def test_builds_with_interactive_cli_interaction(self, mocker, context: AppContext):
        mock_executor: MagicMock = mocker.patch("archcare.cli.context.TaskExecutor")

        context.executor

        _, kwargs = mock_executor.call_args
        interaction = kwargs["interaction"]
        assert isinstance(interaction, CliInteraction)
        assert interaction.is_interactive is True

    def test_registers_all_known_tasks(self, mocker: MagicMock, context: AppContext):
        register_task: MagicMock = mocker.patch.object(TaskExecutor, "register_task")

        context.executor

        assert register_task.call_count == len(_TASK_REGISTRY)

    def test_caches_after_first_access(self, mocker, context: AppContext):
        mock_executor: MagicMock = mocker.patch("archcare.cli.context.TaskExecutor")

        first = context.executor
        second = context.executor

        assert first is second
        mock_executor.assert_called_once()


# ---------------------------------------------------------------------------
# setup_logging
# ---------------------------------------------------------------------------


class TestSetupLogging:
    def test_raises_when_tasks_toml_absent(
        self, context: AppContext, tasks_toml: Path, mock_config_loader: MagicMock
    ):
        # Ensure tasks.toml does NOT exist
        if tasks_toml.exists():
            tasks_toml.unlink()

        with pytest.raises(ConfigNotInitializedError):
            context.setup_logging()

        mock_config_loader.assert_not_called()

    def test_succeeds_when_tasks_toml_present(
        self, mock_setup_logging: MagicMock, context: AppContext
    ):

        # Should not raise
        context.setup_logging()

        # Verify the underlying utility was called
        assert mock_setup_logging.call_count >= 1

    def test_passes_devel_flag_to_logging_setup(self, mock_setup_logging: MagicMock):
        ctx = AppContext(devel=True, user="testuser")
        ctx.setup_logging()

        mock_setup_logging.assert_called_with(ctx.settings, devel_mode=True)

    def test_ensures_directories_exist(self, mock_home: Path):
        ctx = AppContext(devel=False, user="testuser")
        ctx.setup_logging()

        assert (mock_home / ".local/state/archcare/logs").exists()

    def test_does_not_reconfigure_when_settings_match_defaults(
        self, mock_setup_logging: MagicMock, context: AppContext
    ):

        context.setup_logging()

        # Should be called once for defaults
        assert mock_setup_logging.call_count == 1

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

    def test_defaults_to_self_user_when_no_user_param(self, mocker):
        mock_loader: MagicMock = mocker.patch("archcare.cli.context.ConfigLoader")

        ctx = AppContext(devel=False, user="bob")
        ctx.setup_logging()

        assert mock_loader.call_args.kwargs["user"] == "bob"

    def test_passes_explicit_user_to_loader_over_self_user(self, mocker):
        mock_loader: MagicMock = mocker.patch("archcare.cli.context.ConfigLoader")

        ctx = AppContext(devel=False, user="root")
        ctx.setup_logging(user="alice")

        assert mock_loader.call_args.kwargs["user"] == "alice"


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
