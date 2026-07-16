"""Unit tests for the CLI AppContext."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from archcare.cli.context import _TASK_REGISTRY, AppContext
from archcare.cli.interaction import CliInteraction
from archcare.config import AppSettings, LogLevel
from archcare.core.executor import TaskExecutor
from archcare.services.exceptions import ConfigNotInitializedError
from archcare.utils import UserContext

_MODULE = "archcare.cli.context"

# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


def _context(devel: bool = False, user_ctx: UserContext | None = None) -> AppContext:
    return AppContext(devel=devel, user_ctx=user_ctx or UserContext.from_env())


@pytest.fixture
def context() -> AppContext:
    return _context()


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
def per_user_home_dir(monkeypatch, tmp_path) -> Path:
    """
    AppSettings.home_dir resolves the way the real implementation does -
    via SUDO_USER first, falling back to the `user` field - but rooted in
    tmp_path instead of /home. Needed for executor_for_user() tests, where
    that SUDO_USER indirection is the actual behavior under test.
    """

    def home_dir(self) -> Path:
        from os import getenv

        sudo_user = getenv("SUDO_USER")
        if sudo_user:
            return tmp_path / "home" / sudo_user
        return tmp_path / "home" / (self.user or "root")

    monkeypatch.setattr(AppSettings, "home_dir", property(home_dir))
    return tmp_path


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
    return mocker.patch(f"{_MODULE}.setup_logging")


@pytest.fixture
def mock_config_loader_class(mocker) -> MagicMock:
    """The patched ConfigLoader class itself — use for call-count/call-args assertions."""
    return mocker.patch(f"{_MODULE}.ConfigLoader")


@pytest.fixture
def mock_config_loader(mock_config_loader_class: MagicMock) -> MagicMock:
    """The instance ConfigLoader() returns — use for stubbing load_settings()/load_state()."""
    return mock_config_loader_class.return_value


@pytest.fixture
def mock_executor(mocker) -> MagicMock:
    return mocker.patch(f"{_MODULE}.TaskExecutor")


# ---------------------------------------------------------------------------
# is_interactive property
# ---------------------------------------------------------------------------


class TestIsInteractive:
    def test_true_when_user_is_none(self):
        context = _context()
        assert context.is_interactive is True

    def test_false_when_user_is_set(self):
        context = _context(user_ctx=UserContext(archcare_user="alice"))
        assert context.is_interactive is False

    def test_delegates_to_user_context(self):
        """
        is_interactive is a thin delegation to user_context.is_interactive
        now, not an independent check - confirming it actually consults
        user_context rather than happening to agree with it by coincidence.
        """
        user_ctx = UserContext.from_env()
        context = _context(user_ctx=user_ctx)

        assert context.is_interactive is user_ctx.is_interactive


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
    def test_returns_built_executor(
        self, context: AppContext, mock_executor: MagicMock
    ):
        assert context.executor is mock_executor.return_value

    def test_builds_with_loader_settings_and_state(
        self,
        mock_config_loader: MagicMock,
        mock_executor: MagicMock,
        context: AppContext,
    ):
        mock_config_loader.load_settings.return_value = "SETTINGS"
        mock_config_loader.load_state.return_value = "STATE"

        context.executor

        _, kwargs = mock_executor.call_args
        assert kwargs["config_loader"] is mock_config_loader
        assert kwargs["settings"] == "SETTINGS"
        assert kwargs["state"] == "STATE"
        assert kwargs["user_context"] is context.user_ctx

    def test_builds_with_interactive_cli_interaction(
        self, mock_executor: MagicMock, context: AppContext
    ):
        context.executor

        _, kwargs = mock_executor.call_args
        interaction = kwargs["interaction"]
        assert isinstance(interaction, CliInteraction)

    def test_registers_all_known_tasks(self, mocker: MagicMock, context: AppContext):
        register_task: MagicMock = mocker.patch.object(TaskExecutor, "register_task")

        context.executor

        assert register_task.call_count == len(_TASK_REGISTRY)

    def test_caches_after_first_access(
        self, mock_executor: MagicMock, context: AppContext
    ):
        first = context.executor
        second = context.executor

        assert first is second
        mock_executor.assert_called_once()


# ---------------------------------------------------------------------------
# setup_logging
# ---------------------------------------------------------------------------


class TestSetupLogging:
    def test_raises_when_tasks_toml_absent(
        self, context: AppContext, tasks_toml: Path, mock_config_loader_class: MagicMock
    ):
        # Ensure tasks.toml does NOT exist
        if tasks_toml.exists():
            tasks_toml.unlink()

        with pytest.raises(ConfigNotInitializedError):
            context.setup_logging()

        mock_config_loader_class.assert_not_called()

    def test_succeeds_when_tasks_toml_present(
        self, mock_setup_logging: MagicMock, context: AppContext
    ):

        # Should not raise
        context.setup_logging()

        # Verify the underlying utility was called
        assert mock_setup_logging.call_count >= 1

    def test_passes_devel_flag_to_logging_setup(self, mock_setup_logging: MagicMock):
        ctx = _context(devel=True, user_ctx=UserContext(archcare_user="testuser"))
        ctx.setup_logging()

        mock_setup_logging.assert_called_with(ctx.settings, devel_mode=True)

    def test_ensures_directories_exist(self, mock_home: Path):
        ctx = _context(devel=False, user_ctx=UserContext(archcare_user="testuser"))
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
        # Instantiate an AppSetting with different settings
        settings = AppSettings(
            user=context.user_ctx.archcare_user, log_level=LogLevel.DEBUG
        )
        mocker.patch.object(AppContext, "settings", new=settings)

        context.setup_logging()

        # Should be called once for defaults, and a second time for reconfiguration
        assert mock_setup_logging.call_count == 2
        mock_setup_logging.assert_called_with(
            settings, reconfigure=True, devel_mode=False
        )

    def test_defaults_to_self_user_when_no_user_param(
        self, mock_config_loader_class: MagicMock
    ):
        ctx = _context(devel=True, user_ctx=UserContext(archcare_user="bob"))
        ctx.setup_logging()

        assert mock_config_loader_class.call_args.kwargs["user"] == "bob"

    def test_passes_explicit_user_to_loader_over_self_user(
        self, mock_config_loader_class: MagicMock
    ):
        ctx = _context(user_ctx=UserContext(archcare_user="root"))
        ctx.setup_logging(user="alice")

        assert mock_config_loader_class.call_args.kwargs["user"] == "alice"


# ---------------------------------------------------------------------------
# executor_for_user
# ---------------------------------------------------------------------------


class TestExecutorForUser:
    """
    executor_for_user() is used exclusively by `setup timers`, which always
    runs with ctx.obj.user == None (invoked interactively via sudo, never
    through the ARCHCARE_USER systemd path - see setup.py). In that flow,
    setup_logging()'s init-check builds AppSettings(user=self.user) i.e.
    AppSettings(user=None), but home_dir still resolves to the *target*
    user's home because it reads SUDO_USER from the environment regardless
    of the `user` field. The tests below set SUDO_USER to recreate that.
    """

    def _init_target_user_config(self, root: Path, user: str) -> Path:
        config_dir = root / "home" / user / ".config/archcare"
        config_dir.mkdir(parents=True)
        (config_dir / "tasks.toml").touch()
        return config_dir

    def test_resolves_target_user_via_sudo_user_env(
        self,
        per_user_home_dir: Path,
        monkeypatch,
        mock_executor: MagicMock,
        context: AppContext,
    ):
        monkeypatch.setenv("SUDO_USER", "alice")
        self._init_target_user_config(per_user_home_dir, "alice")

        result: TaskExecutor = context.executor_for_user("alice")

        assert result is mock_executor.return_value

    @pytest.mark.usefixtures("per_user_home_dir")
    def test_raises_when_target_users_config_missing(
        self, monkeypatch, context: AppContext
    ):
        monkeypatch.setenv("SUDO_USER", "alice")
        # alice's config dir is deliberately never created.

        with pytest.raises(ConfigNotInitializedError):
            context.executor_for_user("alice")

    def test_does_not_pass_interaction_kwarg(
        self, per_user_home_dir: Path, monkeypatch, mock_executor: MagicMock
    ):
        """
        Unlike the `executor` property, executor_for_user() omits
        `interaction`, so TaskExecutor falls back to its NonInteractive
        default - appropriate for setup timers, which must never block on
        a confirmation prompt mid-install.
        """
        monkeypatch.setenv("SUDO_USER", "alice")
        self._init_target_user_config(per_user_home_dir, "alice")

        ctx = _context()
        ctx.executor_for_user("alice")

        _, kwargs = mock_executor.call_args
        assert "interaction" not in kwargs

    def test_does_not_pass_user_context_kwarg(
        self, per_user_home_dir: Path, monkeypatch, mock_executor: MagicMock
    ):
        """
        Also deliberately omitted: this executor never calls execute_task()
        (only TimerService reads config_loader/state off it), and
        ARCHCARE_USER is always unset in this sudo-driven flow anyway -
        passing user_context here would blur it with the unrelated
        SUDO_USER target being resolved via `user`.
        """
        monkeypatch.setenv("SUDO_USER", "alice")
        self._init_target_user_config(per_user_home_dir, "alice")

        ctx = _context()
        ctx.executor_for_user("alice")

        _, kwargs = mock_executor.call_args
        assert "user_context" not in kwargs

    def test_registers_all_known_tasks(
        self, per_user_home_dir: Path, context: AppContext, monkeypatch, mocker
    ):
        monkeypatch.setenv("SUDO_USER", "alice")
        self._init_target_user_config(per_user_home_dir, "alice")

        register_task: MagicMock = mocker.patch.object(TaskExecutor, "register_task")

        context.executor_for_user("alice")

        assert register_task.call_count == len(_TASK_REGISTRY)

    def test_builds_a_fresh_instance_each_call(
        self,
        monkeypatch,
        per_user_home_dir: Path,
        mock_executor: MagicMock,
        context: AppContext,
    ):
        monkeypatch.setenv("SUDO_USER", "alice")
        self._init_target_user_config(per_user_home_dir, "alice")

        # Instruct the mock to return a brand new MagicMock on every instantiation
        mock_executor.side_effect = [MagicMock(), MagicMock()]

        # Generate a targeted executor
        target_executor = context.executor_for_user("alice")

        # Instantiate the standard context executor
        cached_executor = context.executor

        # They should be distinct instances (TaskExecutor should have been constructed multiple times)
        assert target_executor is not cached_executor
        assert mock_executor.call_count == 2
