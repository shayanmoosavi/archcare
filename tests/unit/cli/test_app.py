"""Unit tests for cli/app.py"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from archcare.cli.app import callback, main
from archcare.services.exceptions import ConfigNotInitializedError
from archcare.utils import UserContext

_MODULE = "archcare.cli.app"
_PATCH_APP = f"{_MODULE}.app"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_context(mocker) -> MagicMock:
    return mocker.patch(f"{_MODULE}.AppContext")


@pytest.fixture
def mock_info(mocker) -> MagicMock:
    return mocker.patch(f"{_MODULE}.print_info")


@pytest.fixture
def mock_error(mocker) -> MagicMock:
    return mocker.patch(f"{_MODULE}.print_error")


@pytest.fixture
def mock_configure_console(mocker) -> MagicMock:
    return mocker.patch(f"{_MODULE}.configure_console")


# ---------------------------------------------------------------------------
# callback
# ---------------------------------------------------------------------------


class TestCallback:
    def test_sets_ctx_obj_to_app_context_instance(self, mock_context: MagicMock):
        ctx = SimpleNamespace()

        callback(ctx)  # ty:ignore[invalid-argument-type]

        assert ctx.obj is mock_context.return_value

    @pytest.mark.parametrize("devel_flag", [True, False])
    def test_devel_flag_passed_through(self, mock_context: MagicMock, devel_flag):
        ctx = SimpleNamespace()

        callback(ctx, devel=devel_flag)  # ty:ignore[invalid-argument-type]

        assert mock_context.call_args.kwargs["devel"] is devel_flag

    def test_user_derived_from_archcare_user_env_var(
        self, mock_context: MagicMock, monkeypatch
    ):
        monkeypatch.setenv("ARCHCARE_USER", "alice")
        ctx = SimpleNamespace()

        callback(ctx)  # ty:ignore[invalid-argument-type]

        user_ctx: UserContext = mock_context.call_args.kwargs["user_ctx"]
        assert user_ctx.archcare_user == "alice"

    def test_user_is_none_when_env_var_unset(self, mock_context: MagicMock):
        ctx = SimpleNamespace()

        callback(ctx)  # ty:ignore[invalid-argument-type]

        user_ctx: UserContext = mock_context.call_args.kwargs["user_ctx"]
        assert user_ctx.archcare_user is None

    @pytest.mark.usefixtures("mock_context")
    def test_configures_console_when_interactive(
        self, mock_configure_console: MagicMock
    ):
        ctx = SimpleNamespace()

        callback(ctx)  # ty:ignore[invalid-argument-type]

        mock_configure_console.assert_called_once_with(True)

    @pytest.mark.usefixtures("mock_context")
    def test_configures_console_when_non_interactive(
        self, mock_configure_console: MagicMock, monkeypatch
    ):
        monkeypatch.setenv("ARCHCARE_USER", "alice")
        ctx = SimpleNamespace()

        callback(ctx)  # ty:ignore[invalid-argument-type]

        mock_configure_console.assert_called_once_with(False)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    def test_success_path_does_not_raise_or_print(
        self, mocker, mock_info: MagicMock, mock_error: MagicMock
    ):
        mocker.patch(_PATCH_APP)

        main()  # must not raise

        mock_error.assert_not_called()
        mock_info.assert_not_called()

    def test_config_not_initialized_shows_messages_and_exits_1(
        self, mocker, mock_info: MagicMock, mock_error: MagicMock
    ):
        mocker.patch(_PATCH_APP, side_effect=ConfigNotInitializedError())

        with pytest.raises(SystemExit) as exc_info:
            main()

        mock_error.assert_called_once_with("Archcare is not initialized.")
        mock_info.assert_called_once_with("Run 'archcare setup config' to get started.")
        assert exc_info.value.code == 1

    def test_generic_exception_shows_error_and_exits_1(
        self, mocker, mock_info: MagicMock, mock_error: MagicMock
    ):
        mocker.patch(_PATCH_APP, side_effect=Exception("disk on fire"))

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert "disk on fire" in mock_error.call_args.args[0]
        mock_info.assert_not_called()
        assert exc_info.value.code == 1
