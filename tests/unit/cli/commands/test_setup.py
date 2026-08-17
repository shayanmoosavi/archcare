"""Unit tests for the `setup` command group."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import typer

from archcare.cli.commands.setup import setup_config, setup_timers
from archcare.services.exceptions import (
    NotRootError,
    SystemdReloadError,
    UserDetectionError,
)

_MODULE = "archcare.cli.commands.setup"

_PATCH_CONFIRM = f"{_MODULE}.typer.confirm"
_PATCH_RESOLVE_USER = f"{_MODULE}.resolve_systemd_target_user"

# ---------------------------------------------------------------------------
# Fixtures and Helpers
# ---------------------------------------------------------------------------


def _make_ctx(app_context=None) -> SimpleNamespace:
    return SimpleNamespace(obj=app_context or MagicMock())


@pytest.fixture
def mock_presenter(mocker) -> MagicMock:
    return mocker.patch(f"{_MODULE}.SetupPresenter")


@pytest.fixture
def mock_config_service(mocker) -> MagicMock:
    return mocker.patch(f"{_MODULE}.ConfigService").return_value


@pytest.fixture
def mock_timer_service(mocker) -> MagicMock:
    return mocker.patch(f"{_MODULE}.TimerService").return_value


# ---------------------------------------------------------------------------
# setup config
# ---------------------------------------------------------------------------


class TestSetupConfig:
    def test_no_existing_files_initializes_without_prompting(
        self, mocker, mock_presenter: MagicMock, mock_config_service: MagicMock
    ):
        mock_confirm: MagicMock = mocker.patch(_PATCH_CONFIRM)
        mock_config_service.check_existing.return_value = []
        mock_config_service.initialize.return_value = "RESULT_SENTINEL"

        setup_config()

        mock_confirm.assert_not_called()
        mock_config_service.initialize.assert_called_once()
        mock_presenter.render_config_init.assert_called_once_with("RESULT_SENTINEL")

    def test_config_header_uses_service_config_dir(
        self, tmp_path, mock_presenter: MagicMock, mock_config_service: MagicMock
    ):
        mock_config_service.check_existing.return_value = []
        mock_config_service.config_dir = tmp_path

        setup_config()

        mock_presenter.config_header.assert_called_once_with(tmp_path)

    def test_existing_files_confirmed_still_initializes(
        self, mocker, mock_presenter: MagicMock, mock_config_service: MagicMock
    ):
        mocker.patch(_PATCH_CONFIRM, return_value=True)
        mock_config_service.check_existing.return_value = ["settings.toml"]

        setup_config()

        mock_presenter.existing_files_warning.assert_called_once_with(["settings.toml"])
        mock_config_service.initialize.assert_called_once_with(force=True)
        mock_presenter.render_config_init.assert_called_once()

    def test_existing_files_declined_passes_force_false(
        self, mocker, mock_presenter: MagicMock, mock_config_service: MagicMock
    ):
        mocker.patch(_PATCH_CONFIRM, return_value=False)
        mock_config_service.check_existing.return_value = ["settings.toml"]

        setup_config()

        mock_config_service.initialize.assert_called_once_with(force=False)
        mock_presenter.render_config_init.assert_called_once()


# ---------------------------------------------------------------------------
# setup timers - user resolution
# ---------------------------------------------------------------------------


class TestSetupTimersUserResolution:
    def test_not_root_error_shows_not_root_and_exits_1(self, mocker, mock_presenter: MagicMock):
        mocker.patch(_PATCH_RESOLVE_USER, side_effect=NotRootError())
        ctx = _make_ctx()

        with pytest.raises(typer.Exit) as exc_info:
            setup_timers(ctx)  # ty:ignore[invalid-argument-type]

        mock_presenter.not_root.assert_called_once()
        assert exc_info.value.exit_code == 1

    def test_user_detection_error_shows_message_and_exits_1(
        self, mocker, mock_presenter: MagicMock
    ):
        mocker.patch(
            _PATCH_RESOLVE_USER,
            side_effect=UserDetectionError("SUDO_USER not set"),
        )
        ctx = _make_ctx()

        with pytest.raises(typer.Exit) as exc_info:
            setup_timers(ctx)  # ty:ignore[invalid-argument-type]

        assert "SUDO_USER not set" in mock_presenter.error.call_args.args[0]
        assert exc_info.value.exit_code == 1


# ---------------------------------------------------------------------------
# setup timers - main flow
# ---------------------------------------------------------------------------


class TestSetupTimersMainFlow:
    @pytest.fixture(autouse=True)
    def resolved_user(self, mocker):
        """Every test in this class needs user resolution to succeed."""
        mocker.patch(
            _PATCH_RESOLVE_USER,
            return_value=("alice", "/home/alice"),
        )

    @pytest.mark.usefixtures("mock_presenter")
    def test_executor_built_for_resolved_user_not_ctx_own_user(self, mock_timer_service: MagicMock):
        """
        Confirms the comment in setup.py: executor_for_user(user) uses the
        resolved SUDO_USER target, not ctx.obj's own user.
        """
        mock_timer_service.get_automated_tasks.return_value = {}
        ctx = _make_ctx()

        setup_timers(ctx)  # ty:ignore[invalid-argument-type]

        ctx.obj.executor_for_user.assert_called_once_with("alice")

    @pytest.mark.usefixtures("mock_presenter")
    def test_timer_service_built_with_executor_user_and_home_dir(self, mocker):
        mock_timer_service_class: MagicMock = mocker.patch(f"{_MODULE}.TimerService")
        mock_timer_service_class.return_value.get_automated_tasks.return_value = {}
        ctx = _make_ctx()
        ctx.obj.executor_for_user.return_value = "EXECUTOR_SENTINEL"

        setup_timers(ctx)  # ty:ignore[invalid-argument-type]

        mock_timer_service_class.assert_called_once_with(
            "EXECUTOR_SENTINEL", "alice", "/home/alice"
        )

    def test_automated_tasks_present_calls_setup_timers_and_renders(
        self, mock_presenter: MagicMock, mock_timer_service: MagicMock
    ):
        mock_timer_service.get_automated_tasks.return_value = {"update-mirrorlist": object()}
        mock_timer_service.setup_timers.return_value = "SETUP_RESPONSE_SENTINEL"
        ctx = _make_ctx()

        setup_timers(ctx, enable=True, dry_run=False)  # ty:ignore[invalid-argument-type]

        mock_timer_service.setup_timers.assert_called_once_with(
            mock_timer_service.get_automated_tasks.return_value, False, True
        )
        mock_presenter.render_timer_setup.assert_called_once_with("SETUP_RESPONSE_SENTINEL")
        mock_presenter.no_automated_tasks.assert_not_called()

    def test_no_automated_tasks_shows_message_without_calling_setup_timers(
        self, mock_presenter: MagicMock, mock_timer_service: MagicMock
    ):
        mock_timer_service.get_automated_tasks.return_value = {}
        ctx = _make_ctx()

        setup_timers(ctx)  # ty:ignore[invalid-argument-type]

        mock_presenter.no_automated_tasks.assert_called_once()
        mock_timer_service.setup_timers.assert_not_called()

    def test_dry_run_true_shows_dry_run_notice(
        self, mock_presenter: MagicMock, mock_timer_service: MagicMock
    ):
        mock_timer_service.get_automated_tasks.return_value = {}
        ctx = _make_ctx()

        setup_timers(ctx, dry_run=True)  # ty:ignore[invalid-argument-type]

        mock_presenter.dry_run_notice.assert_called_once()

    def test_dry_run_false_does_not_show_notice(
        self, mock_presenter: MagicMock, mock_timer_service: MagicMock
    ):
        mock_timer_service.get_automated_tasks.return_value = {}
        ctx = _make_ctx()

        setup_timers(ctx, dry_run=False)  # ty:ignore[invalid-argument-type]

        mock_presenter.dry_run_notice.assert_not_called()

    def test_systemd_reload_error_shows_message_and_exits_1(
        self, mock_presenter: MagicMock, mock_timer_service: MagicMock
    ):
        mock_timer_service.install_templates.side_effect = SystemdReloadError()
        ctx = _make_ctx()

        with pytest.raises(typer.Exit) as exc_info:
            setup_timers(ctx)  # ty:ignore[invalid-argument-type]

        assert "Failed to reload systemd" in mock_presenter.error.call_args.args[0]
        assert exc_info.value.exit_code == 1

    def test_generic_exception_shows_error_and_exits_1(
        self, mocker, mock_presenter: MagicMock, mock_timer_service: MagicMock
    ):
        mocker.patch(f"{_MODULE}.logger")
        mock_timer_service.install_templates.side_effect = RuntimeError("disk on fire")
        ctx = _make_ctx()

        with pytest.raises(typer.Exit) as exc_info:
            setup_timers(ctx)  # ty:ignore[invalid-argument-type]

        assert "disk on fire" in mock_presenter.error.call_args.args[0]
        assert exc_info.value.exit_code == 1
