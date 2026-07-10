"""Unit tests for SetupPresenter."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from archcare.cli.presenters.setup_presenter import SetupPresenter, _list_timers
from archcare.config import TaskConfig
from archcare.services.responses import (
    ConfigInitResponse,
    InstallTemplatesResponse,
    ReloadSystemdResponse,
    TimerEnableResponse,
    TimerSetupResponse,
)

_MODULE = "archcare.cli.presenters.setup_presenter"

_PATCH_WARNINGS = f"{_MODULE}.print_warning"
_PATCH_SUCCESS = f"{_MODULE}.print_success"
_PATCH_CONSOLE = f"{_MODULE}.console"

# ---------------------------------------------------------------------------
# Fixtures and Helpers
# ---------------------------------------------------------------------------


def _timer_setup_response(**overrides) -> TimerSetupResponse:
    defaults: dict[str, Any] = {
        "automated_tasks": {},
        "enabled_timers": [],
        "timer_status": None,
    }
    return TimerSetupResponse(**{**defaults, **overrides})


def _was_called_with(mock, *args, **kwargs) -> bool:
    """Check call_args_list for an exact (args, kwargs) match, since some
    tests need to assert a *specific* call is absent among many other
    unrelated print/print_info calls the same method makes."""
    return any(c.args == args and c.kwargs == kwargs for c in mock.call_args_list)


@pytest.fixture(autouse=True)
def mock_info(mocker) -> MagicMock:
    return mocker.patch(f"{_MODULE}.print_info")


@pytest.fixture
def mock_warning(mocker) -> MagicMock:
    return mocker.patch(_PATCH_WARNINGS)


@pytest.fixture
def mock_success(mocker) -> MagicMock:
    return mocker.patch(_PATCH_SUCCESS)


@pytest.fixture(autouse=True)
def mock_print(mocker) -> MagicMock:
    return mocker.patch(f"{_MODULE}.console.print")


# ---------------------------------------------------------------------------
# setup config
# ---------------------------------------------------------------------------


class TestExistingFilesWarning:
    def test_prints_warning_header(self, mock_warning: MagicMock):

        SetupPresenter.existing_files_warning([])

        mock_warning.assert_called_once_with("Configuration files already exist:")

    def test_prints_each_file_name(self, tmp_path, mocker, mock_print: MagicMock):
        mocker.patch(_PATCH_WARNINGS)

        files = [tmp_path / "settings.toml", tmp_path / "tasks.toml"]
        SetupPresenter.existing_files_warning(files)

        assert mock_print.call_count == 2
        assert "settings.toml" in mock_print.call_args_list[0].args[0]
        assert "tasks.toml" in mock_print.call_args_list[1].args[0]

    def test_no_file_lines_when_list_empty(self, mocker, mock_print: MagicMock):
        mocker.patch(_PATCH_WARNINGS)

        SetupPresenter.existing_files_warning([])

        mock_print.assert_not_called()


class TestRenderConfigInit:
    @pytest.mark.usefixtures("mock_success")
    def test_prints_created_files(self, tmp_path, mock_print: MagicMock):

        SetupPresenter.render_config_init(
            ConfigInitResponse(
                config_dir=tmp_path,
                created_files=[tmp_path / "settings.toml"],
                skipped_files=[],
            )
        )

        assert "settings.toml" in mock_print.call_args_list[0].args[0]

    def test_prints_skipped_files(self, tmp_path, mock_print: MagicMock):
        SetupPresenter.render_config_init(
            ConfigInitResponse(
                config_dir=tmp_path,
                created_files=[],
                skipped_files=[tmp_path / "tasks.toml"],
            )
        )

        assert "tasks.toml" in mock_print.call_args_list[0].args[0]

    @pytest.mark.usefixtures("mock_success")
    def test_prints_both_created_and_skipped_files(
        self, tmp_path, mock_print: MagicMock
    ):
        SetupPresenter.render_config_init(
            ConfigInitResponse(
                config_dir=tmp_path,
                created_files=[tmp_path / "settings.toml"],
                skipped_files=[tmp_path / "tasks.toml"],
            )
        )

        assert "settings.toml" in mock_print.call_args_list[0].args[0]
        assert "tasks.toml" in mock_print.call_args_list[1].args[0]


# ---------------------------------------------------------------------------
# setup timers - template installation / reload
# ---------------------------------------------------------------------------


class TestRenderTemplateInstallation:
    @pytest.mark.parametrize(
        "dry_run,expected_verb", [(True, "Would create"), (False, "Created")]
    )
    def test_verb_matches_dry_run_flag(
        self, tmp_path, dry_run, expected_verb, mock_success: MagicMock
    ):

        response = InstallTemplatesResponse(
            service_file=tmp_path / "archcare.service",
            timer_file=tmp_path / "archcare.timer",
            dry_run=dry_run,
        )
        SetupPresenter.render_template_installation(response)

        assert expected_verb in mock_success.call_args_list[0].args[0]
        assert expected_verb in mock_success.call_args_list[1].args[0]

    def test_mentions_both_file_paths(self, tmp_path, mocker, mock_info: MagicMock):
        mocker.patch(_PATCH_SUCCESS)

        response = InstallTemplatesResponse(
            service_file=tmp_path / "archcare.service",
            timer_file=tmp_path / "archcare.timer",
            dry_run=False,
        )
        SetupPresenter.render_template_installation(response)

        assert str(response.service_file) in mock_info.call_args_list[0].args[0]
        assert str(response.timer_file) in mock_info.call_args_list[1].args[0]


class TestRenderSystemdReload:
    @pytest.mark.parametrize(
        "dry_run,expected_verb", [(True, "Would reload"), (False, "Reloaded")]
    )
    def test_success_verbs_match_dry_run_flag(
        self, dry_run, expected_verb, mock_success: MagicMock
    ):

        SetupPresenter.render_systemd_reload(ReloadSystemdResponse(dry_run=dry_run))

        assert expected_verb in mock_success.call_args.args[0]


# ---------------------------------------------------------------------------
# setup timers - render_timer_setup
#
# NOTE: render_timer_setup calls next(iter(automated_tasks.keys())) with no
# default, so an empty automated_tasks dict would raise StopIteration. The
# only caller (setup.py's `setup timers` command) already guards this by
# only invoking render_timer_setup when automated_tasks is non-empty, so
# it's not currently reachable - not tested here, just noted.
# ---------------------------------------------------------------------------


class TestRenderTimerSetup:
    @pytest.fixture
    @staticmethod
    def mock_list_timers(mocker) -> MagicMock:
        return mocker.patch(f"{_MODULE}._list_timers")

    @pytest.mark.parametrize(
        "task_fixture,expected_icon",
        [
            ("automated_task", "✓"),
            ("disabled_task", "✗"),
        ],
    )
    def test_tasks_show_correct_icon(
        self, task_fixture, expected_icon, request, mock_print: MagicMock
    ):

        task: TaskConfig = request.getfixturevalue(task_fixture)
        response = _timer_setup_response(automated_tasks={task.name: task})
        SetupPresenter.render_timer_setup(response)

        # index [0] is the bare print() blank line at the top of the method;
        # the task icon line is the first *non-empty* call, index [1].
        task_line = mock_print.call_args_list[1].args[0]
        assert expected_icon in task_line
        assert task.name in task_line

    def test_example_command_uses_first_task_name(
        self, automated_task: TaskConfig, mock_print: MagicMock
    ):

        response = _timer_setup_response(
            automated_tasks={automated_task.name: automated_task}
        )
        SetupPresenter.render_timer_setup(response)

        joined = "\n".join(c.args[0] for c in mock_print.call_args_list if c.args)
        assert f"archcare@{automated_task.name}.timer" in joined

    def test_list_timers_called_when_enabled_timers_present(
        self, automated_task: TaskConfig, mocker, mock_list_timers: MagicMock
    ):
        mocker.patch(_PATCH_CONSOLE)

        enabled = [TimerEnableResponse(timer_name="archcare@x.timer", enabled=True)]
        response = _timer_setup_response(
            automated_tasks={automated_task.name: automated_task},
            enabled_timers=enabled,
        )
        SetupPresenter.render_timer_setup(response)

        mock_list_timers.assert_called_once_with(response)

    def test_list_timers_not_called_when_enabled_timers_empty(
        self, automated_task: TaskConfig, mock_list_timers: MagicMock
    ):

        response = _timer_setup_response(
            automated_tasks={automated_task.name: automated_task}, enabled_timers=[]
        )
        SetupPresenter.render_timer_setup(response)

        mock_list_timers.assert_not_called()

    def test_timer_status_block_shown_when_present(
        self, automated_task: TaskConfig, mocker, mock_info: MagicMock
    ):
        mocker.patch(_PATCH_CONSOLE)

        response = _timer_setup_response(
            automated_tasks={automated_task.name: automated_task},
            timer_status="archcare@x.timer  active",
        )
        SetupPresenter.render_timer_setup(response)

        assert _was_called_with(mock_info, "Timer Status")

    def test_timer_status_block_skipped_when_absent(
        self, automated_task: TaskConfig, mock_info: MagicMock
    ):

        response = _timer_setup_response(
            automated_tasks={automated_task.name: automated_task}, timer_status=None
        )
        SetupPresenter.render_timer_setup(response)

        assert not _was_called_with(mock_info, "Timer Status")


# ---------------------------------------------------------------------------
# Static / no-logic methods - smoke tests only
# ---------------------------------------------------------------------------


class TestStaticMethods:
    @pytest.fixture
    @staticmethod
    def mock_error(mocker) -> MagicMock:
        return mocker.patch(f"{_MODULE}.print_error")

    def test_config_header(self, tmp_path, mocker, mock_info: MagicMock):
        mocker.patch(f"{_MODULE}.print_header")

        SetupPresenter.config_header(tmp_path)

        assert str(tmp_path) in mock_info.call_args.args[0]

    def test_templates_installed(self, mocker, mock_success: MagicMock):
        mocker.patch(_PATCH_CONSOLE)

        SetupPresenter.templates_installed()

        mock_success.assert_called_once()

    def test_no_automated_tasks(self, mock_warning: MagicMock):

        SetupPresenter.no_automated_tasks()

        mock_warning.assert_called_once()

    def test_useful_commands(self, mock_print: MagicMock):
        SetupPresenter.useful_commands()

        assert mock_print.call_count > 0

    def test_dry_run_notice(self, mock_success: MagicMock):

        SetupPresenter.dry_run_notice()

        mock_success.assert_called_once()

    def test_not_root_message(self, mock_error: MagicMock):
        SetupPresenter.not_root()

        assert "sudo" in mock_error.call_args[0][0]

    def test_error_passes_through_message(self, mock_error: MagicMock):
        SetupPresenter.error("boom")

        mock_error.assert_called_once_with("boom")


# ---------------------------------------------------------------------------
# _list_timers
# ---------------------------------------------------------------------------


class TestListTimers:
    def test_enabled_timer_prints_success(self, mocker, mock_success: MagicMock):
        mocker.patch(_PATCH_WARNINGS)

        response = _timer_setup_response(
            enabled_timers=[
                TimerEnableResponse(timer_name="archcare@foo.timer", enabled=True)
            ]
        )
        _list_timers(response)

        assert "archcare@foo.timer" in mock_success.call_args.args[0]

    def test_failed_timer_prints_warning(self, mocker, mock_warning: MagicMock):
        mocker.patch(_PATCH_SUCCESS)

        response = _timer_setup_response(
            enabled_timers=[
                TimerEnableResponse(timer_name="archcare@bar.timer", enabled=False)
            ]
        )
        _list_timers(response)

        assert "archcare@bar.timer" in mock_warning.call_args.args[0]
