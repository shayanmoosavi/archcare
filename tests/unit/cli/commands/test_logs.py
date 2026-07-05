"""Unit tests for the `logs` command."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import typer

from archcare.cli.commands.logs import logs

_MODULE = "archcare.cli.commands.logs"


def _make_ctx(invoked_subcommand=None) -> SimpleNamespace:
    return SimpleNamespace(obj=MagicMock(), invoked_subcommand=invoked_subcommand)


class TestLogsCallback:
    def test_returns_early_when_subcommand_invoked(self, mocker):
        mocker.patch(f"{_MODULE}.print_header")
        ctx = _make_ctx(invoked_subcommand="clear")

        logs(ctx)  # ty:ignore[invalid-argument-type]

        ctx.obj.setup_logging.assert_not_called()

    def test_main_log_used_when_no_task_name(self, tmp_path: Path, mocker):
        mocker.patch(f"{_MODULE}.print_header")
        ctx = _make_ctx()
        ctx.obj.executor.settings.log_dir = tmp_path
        (tmp_path / "archcare.log").write_text("line1\nline2\n")

        # Must not raise / not hit the missing-file branch
        logs(ctx)  # ty:ignore[invalid-argument-type]

    def test_task_log_used_when_task_name_given(self, tmp_path: Path, mocker):
        mocker.patch(f"{_MODULE}.print_header")
        ctx = _make_ctx()
        ctx.obj.executor.settings.log_dir = tmp_path
        task_log_dir = tmp_path / "tasks"
        task_log_dir.mkdir()
        (task_log_dir / "update-mirrorlist.log").write_text("line1\n")

        # Must not raise
        logs(ctx, task_name="update-mirrorlist")  # ty:ignore[invalid-argument-type]

    def test_missing_log_file_shows_error_and_exits_1(self, tmp_path: Path, mocker):
        mock_error: MagicMock = mocker.patch(f"{_MODULE}.print_error")
        ctx = _make_ctx()
        ctx.obj.executor.settings.log_dir = tmp_path  # empty - no log file exists

        with pytest.raises(typer.Exit) as exc_info:
            logs(ctx)  # ty:ignore[invalid-argument-type]

        assert "archcare.log" in mock_error.call_args.args[0]
        assert exc_info.value.exit_code == 1

    def test_prints_header_with_log_filename(self, tmp_path: Path, mocker):
        mock_header: MagicMock = mocker.patch(f"{_MODULE}.print_header")
        ctx = _make_ctx()
        ctx.obj.executor.settings.log_dir = tmp_path
        (tmp_path / "archcare.log").write_text("line1\n")

        logs(ctx)  # ty:ignore[invalid-argument-type]

        mock_header.assert_called_once_with("Logs: archcare.log")

    def test_shows_last_n_lines_only(self, tmp_path: Path, capsys, mocker):
        mocker.patch(f"{_MODULE}.print_header")
        ctx = _make_ctx()
        ctx.obj.executor.settings.log_dir = tmp_path
        (tmp_path / "archcare.log").write_text("line1\nline2\nline3\nline4\nline5\n")

        logs(ctx, lines=2)  # ty:ignore[invalid-argument-type]

        out = capsys.readouterr().out
        assert "line4" in out and "line5" in out
        assert "line1" not in out and "line2" not in out and "line3" not in out

    def test_shows_all_lines_when_fewer_than_requested(
        self, tmp_path: Path, capsys, mocker
    ):
        """
        Confirming the app doesn't crash or drop lines
        when a log file is shorter than the requested tail length.
        """
        mocker.patch(f"{_MODULE}.print_header")
        ctx = _make_ctx()
        ctx.obj.executor.settings.log_dir = tmp_path
        (tmp_path / "archcare.log").write_text("line1\nline2\n")

        logs(ctx, lines=50)  # ty:ignore[invalid-argument-type]

        out = capsys.readouterr().out
        assert "line1" in out and "line2" in out
