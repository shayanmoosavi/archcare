"""Unit tests for MaintenanceCheckPresenter."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from archcare.cli.presenters.maintenance_presenter import MaintenanceCheckPresenter
from archcare.config import TaskStatus
from archcare.core import (
    IssueSeverity,
    MaintenanceCheckDetails,
    MaintenanceCheckSummary,
    MaintenanceIssue,
)

_MODULE = "archcare.cli.presenters.maintenance_presenter"

_PATCH_TABLE = f"{_MODULE}.Table"
_PATCH_PANEL = f"{_MODULE}.Panel"

# ---------------------------------------------------------------------------
# Fixtures and Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def critical_issue() -> MaintenanceIssue:
    return MaintenanceIssue(
        task_name="update-mirrorlist",
        severity=IssueSeverity.CRITICAL,
        description="Mirrorlist is 20 days overdue",
        days_overdue=20,
        last_run=datetime(2026, 6, 1),
        last_status=TaskStatus.FAILURE,
        recommendation="Run the mirrorlist update immediately",
    )


@pytest.fixture
def warning_issue() -> MaintenanceIssue:
    return MaintenanceIssue(
        task_name="health-check",
        severity=IssueSeverity.WARNING,
        description="Disk usage at 85%",
        recommendation="Review disk usage and clean up if needed",
    )


@pytest.fixture
def info_issue() -> MaintenanceIssue:
    return MaintenanceIssue(
        task_name="failed-services",
        severity=IssueSeverity.INFO,
        description="Last check was 3 days ago",
        recommendation="No action needed",
    )


def _details(
    critical_issues: list[MaintenanceIssue] = [],
    warning_issues: list[MaintenanceIssue] = [],
    info_issues: list[MaintenanceIssue] = [],
) -> MaintenanceCheckDetails:
    return MaintenanceCheckDetails(
        critical_issues=critical_issues,
        warning_issues=warning_issues,
        info_issues=info_issues,
        summary=MaintenanceCheckSummary(
            total_tasks_monitored=3,
            critical_count=len(critical_issues),
            warning_count=len(warning_issues),
            info_count=len(info_issues),
        ),
    )


@pytest.fixture
def mock_console(mocker) -> MagicMock:
    return mocker.patch(f"{_MODULE}.console")


@pytest.fixture
def mock_table(mocker) -> MagicMock:
    """The instance `table = Table()` resolves to inside _render_issues_table()."""
    return mocker.patch(_PATCH_TABLE).return_value


# ---------------------------------------------------------------------------
# render() - no issues
# ---------------------------------------------------------------------------


class TestRenderNoIssues:
    def test_shows_healthy_panel(self, mock_console: MagicMock, mocker):
        mock_panel: MagicMock = mocker.patch(_PATCH_PANEL)

        MaintenanceCheckPresenter.render(_details())

        msg = "✓ No maintenance issues found! Your system is healthy :)"
        mock_panel.assert_called_once_with(
            msg, style="green", border_style="green", width=len(msg) + 4
        )
        mock_console.print.assert_any_call(mock_panel.return_value)

    @pytest.mark.usefixtures("mock_console")
    def test_returns_before_rendering_issue_tables(self, mocker):
        mocker.patch(_PATCH_PANEL)
        mock_render_table: MagicMock = mocker.patch.object(
            MaintenanceCheckPresenter, "_render_issues_table"
        )

        MaintenanceCheckPresenter.render(_details())

        mock_render_table.assert_not_called()

    def test_never_shows_acknowledgment_prompt(self, mock_console: MagicMock, mocker):
        mocker.patch(_PATCH_PANEL)

        MaintenanceCheckPresenter.render(
            _details(), is_interactive=True, require_acknowledgment=True
        )

        mock_console.input.assert_not_called()


# ---------------------------------------------------------------------------
# render() - issue table dispatch
# ---------------------------------------------------------------------------


class TestRenderIssueDispatch:
    def test_critical_issues_render_table(
        self, mock_console: MagicMock, critical_issue: MaintenanceIssue, mocker
    ):
        mock_render_table: MagicMock = mocker.patch.object(
            MaintenanceCheckPresenter, "_render_issues_table"
        )

        result = _details(critical_issues=[critical_issue])
        MaintenanceCheckPresenter.render(result)

        mock_render_table.assert_called_once_with(
            mock_console,
            title="🟥 Critical Issues",
            issues=[critical_issue],
            style="red",
        )

    @pytest.mark.parametrize(
        "issue_fixture,title,style",
        [
            ("critical_issue", "🟥 Critical Issues", "red"),
            ("warning_issue", "🟨 Warning Issues", "yellow"),
            ("info_issue", "🟦 Information", "blue"),
        ],
    )
    def test_issues_render_table(
        self,
        mock_console: MagicMock,
        request,
        mocker,
        issue_fixture: str,
        title: str,
        style: str,
    ):
        """Parametrized test covering critical, warning and info issue tables."""
        mock_render_table = mocker.patch.object(
            MaintenanceCheckPresenter, "_render_issues_table"
        )

        # Resolve the requested issue fixture to get the MaintenanceIssue instance
        issue = request.getfixturevalue(issue_fixture)

        # Build the kwarg name expected by _details (e.g. 'critical_issues')
        key = f"{issue_fixture.split('_')[0]}_issues"
        details = _details(**{key: [issue]})

        MaintenanceCheckPresenter.render(details)

        mock_render_table.assert_called_once_with(
            mock_console, title=title, issues=[issue], style=style
        )

    @pytest.mark.usefixtures("mock_console")
    def test_all_three_severities_render_in_order(
        self,
        critical_issue: MaintenanceIssue,
        warning_issue: MaintenanceIssue,
        info_issue: MaintenanceIssue,
        mocker,
    ):
        mock_render_table: MagicMock = mocker.patch.object(
            MaintenanceCheckPresenter, "_render_issues_table"
        )

        details = _details(
            critical_issues=[critical_issue],
            warning_issues=[warning_issue],
            info_issues=[info_issue],
        )
        MaintenanceCheckPresenter.render(details)

        assert mock_render_table.call_count == 3
        titles = [call.kwargs["title"] for call in mock_render_table.call_args_list]
        assert titles == ["🟥 Critical Issues", "🟨 Warning Issues", "🟦 Information"]


# ---------------------------------------------------------------------------
# render() - acknowledgment prompt
# ---------------------------------------------------------------------------


class TestRenderAcknowledgmentPrompt:
    """
    The prompt requires all three of: critical_issues non-empty,
    require_acknowledgment=True, and is_interactive=True. Each test below
    fails exactly one of those three, to make sure the condition is a
    genuine AND rather than accidentally being satisfied by any one of them.
    """

    def test_shown_when_all_conditions_met(
        self, mock_console: MagicMock, critical_issue: MaintenanceIssue, mocker
    ):
        mocker.patch.object(MaintenanceCheckPresenter, "_render_issues_table")

        details = _details(critical_issues=[critical_issue])
        MaintenanceCheckPresenter.render(
            details, is_interactive=True, require_acknowledgment=True
        )

        mock_console.input.assert_called_once_with("Press Enter to acknowledge... ")

    def test_skipped_when_acknowledgment_not_required(
        self, mock_console: MagicMock, critical_issue: MaintenanceIssue, mocker
    ):
        mocker.patch.object(MaintenanceCheckPresenter, "_render_issues_table")

        details = _details(critical_issues=[critical_issue])
        MaintenanceCheckPresenter.render(
            details, is_interactive=True, require_acknowledgment=False
        )

        mock_console.input.assert_not_called()

    def test_skipped_when_not_interactive(
        self, mock_console: MagicMock, critical_issue: MaintenanceIssue, mocker
    ):
        """
        The important safety case: a systemd/non-interactive run must
        never block waiting on stdin for an acknowledgment nobody can give.
        """
        mocker.patch.object(MaintenanceCheckPresenter, "_render_issues_table")

        details = _details(critical_issues=[critical_issue])
        MaintenanceCheckPresenter.render(
            details, is_interactive=False, require_acknowledgment=True
        )

        mock_console.input.assert_not_called()

    def test_skipped_when_no_critical_issues(
        self, mock_console: MagicMock, warning_issue: MaintenanceIssue, mocker
    ):
        """has_issues is True (a warning exists), but critical_issues is
        empty - the prompt must not fire on warnings/info alone."""
        mocker.patch.object(MaintenanceCheckPresenter, "_render_issues_table")

        details = _details(warning_issues=[warning_issue])
        MaintenanceCheckPresenter.render(
            details, is_interactive=True, require_acknowledgment=True
        )

        mock_console.input.assert_not_called()


# ---------------------------------------------------------------------------
# _render_issues_table
# ---------------------------------------------------------------------------


class TestRenderIssuesTable:
    def test_constructs_table_with_title_and_style(
        self, mocker, mock_console: MagicMock
    ):
        mock_table: MagicMock = mocker.patch(f"{_MODULE}.Table")

        MaintenanceCheckPresenter._render_issues_table(
            mock_console, title="🟥 Critical Issues", issues=[], style="red"
        )

        mock_table.assert_called_once_with(
            title="🟥 Critical Issues", show_header=True, border_style="red"
        )

    def test_adds_three_columns(self, mock_console: MagicMock, mock_table: MagicMock):

        MaintenanceCheckPresenter._render_issues_table(
            mock_console, title="X", issues=[], style="red"
        )

        assert mock_table.add_column.call_count == 3
        column_names = [c.args[0] for c in mock_table.add_column.call_args_list]
        assert column_names == ["Task", "Issue", "Recommendation"]

    def test_adds_one_row_per_issue_with_correct_field_mapping(
        self,
        critical_issue: MaintenanceIssue,
        warning_issue: MaintenanceIssue,
        mock_console: MagicMock,
        mock_table: MagicMock,
    ):
        """
        Pins down task_name/description/recommendation -> column mapping
        specifically, since a swapped description/recommendation argument
        order would be a silent, easy-to-make bug that no type checker
        would catch (all three fields are plain strings).
        """

        MaintenanceCheckPresenter._render_issues_table(
            mock_console,
            title="X",
            issues=[critical_issue, warning_issue],
            style="red",
        )

        assert mock_table.add_row.call_count == 2
        mock_table.add_row.assert_any_call(
            critical_issue.task_name,
            critical_issue.description,
            critical_issue.recommendation,
        )
        mock_table.add_row.assert_any_call(
            warning_issue.task_name,
            warning_issue.description,
            warning_issue.recommendation,
        )

    def test_prints_table_then_blank_line(
        self, mocker, mock_console: MagicMock, mock_table: MagicMock
    ):

        MaintenanceCheckPresenter._render_issues_table(
            mock_console, title="X", issues=[], style="red"
        )

        assert mock_console.print.call_args_list[0] == mocker.call(mock_table)
        assert mock_console.print.call_args_list[1] == mocker.call()
