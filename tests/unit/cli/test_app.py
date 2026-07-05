"""Unit tests for cli/app.py"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import typer

from archcare.cli.app import callback, main
from archcare.services.exceptions import ConfigNotInitializedError

_MODULE = "archcare.cli.app"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_context(mocker) -> MagicMock:
    return mocker.patch(f"{_MODULE}.AppContext")


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

        assert mock_context.call_args.kwargs["user"] == "alice"

    def test_user_is_none_when_env_var_unset(self, mock_context: MagicMock):
        ctx = SimpleNamespace()

        callback(ctx)  # ty:ignore[invalid-argument-type]

        assert mock_context.call_args.kwargs["user"] is None


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    def test_success_path_does_not_raise_or_print(self, mocker):
        mocker.patch(f"{_MODULE}.app")
        mock_error: MagicMock = mocker.patch(f"{_MODULE}.print_error")
        mock_info: MagicMock = mocker.patch(f"{_MODULE}.print_info")

        main()  # must not raise

        mock_error.assert_not_called()
        mock_info.assert_not_called()

    def test_config_not_initialized_shows_messages_and_exits_1(self, mocker):
        mocker.patch(f"{_MODULE}.app", side_effect=ConfigNotInitializedError())
        mock_error = mocker.patch(f"{_MODULE}.print_error")
        mock_info = mocker.patch(f"{_MODULE}.print_info")

        with pytest.raises(typer.Exit) as exc_info:
            main()

        mock_error.assert_called_once_with("Archcare is not initialized.")
        mock_info.assert_called_once_with("Run 'archcare setup config' to get started.")
        assert exc_info.value.exit_code == 1
