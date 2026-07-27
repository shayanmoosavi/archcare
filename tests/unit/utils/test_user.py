"""Unit tests for UserContext."""

from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from archcare.utils import UserContext

_MODULE = "archcare.utils.user"

# ---------------------------------------------------------------------------
# is_interactive
# ---------------------------------------------------------------------------


class TestIsInteractive:
    def test_true_when_archcare_user_is_none(self):
        assert UserContext(archcare_user=None).is_interactive is True

    def test_false_when_archcare_user_is_set(self):
        assert UserContext(archcare_user="alice").is_interactive is False


# ---------------------------------------------------------------------------
# from_env
# ---------------------------------------------------------------------------


class TestFromEnv:
    def test_resolves_none_when_unset(self, monkeypatch):
        monkeypatch.delenv("ARCHCARE_USER", raising=False)

        assert UserContext.from_env().archcare_user is None

    def test_resolves_value_when_set(self, monkeypatch):
        monkeypatch.setenv("ARCHCARE_USER", "alice")

        assert UserContext.from_env().archcare_user == "alice"


# ---------------------------------------------------------------------------
# chown_if_root
# ---------------------------------------------------------------------------


class TestChownIfRoot:
    @pytest.fixture
    def mock_chown(self, mocker) -> MagicMock:
        return mocker.patch(f"{_MODULE}.change_ownership_to_user")

    def test_no_op_when_not_root(self, mocker, tmp_path: Path, mock_chown: MagicMock):
        mocker.patch(f"{_MODULE}.is_root", return_value=False)

        UserContext(archcare_user="alice").chown_if_root(tmp_path / "file.txt")

        mock_chown.assert_not_called()

    def test_no_op_when_archcare_user_absent(
        self, mocker, tmp_path: Path, mock_chown: MagicMock
    ):
        mocker.patch(f"{_MODULE}.is_root", return_value=True)

        UserContext(archcare_user=None).chown_if_root(tmp_path / "file.txt")

        mock_chown.assert_not_called()

    def test_chowns_every_path_when_root_and_archcare_user_set(
        self, mocker, tmp_path: Path, mock_chown: MagicMock
    ):
        mocker.patch(f"{_MODULE}.is_root", return_value=True)

        file_path = tmp_path / "state.json"
        parent_path = tmp_path

        UserContext(archcare_user="alice").chown_if_root(file_path, parent_path)

        assert mock_chown.call_count == 2
        mock_chown.assert_any_call(file_path, "alice")
        mock_chown.assert_any_call(parent_path, "alice")

    def test_handles_single_path(self, mocker, tmp_path: Path, mock_chown: MagicMock):
        mocker.patch(f"{_MODULE}.is_root", return_value=True)

        UserContext(archcare_user="alice").chown_if_root(tmp_path / "file.txt")

        mock_chown.assert_called_once_with(tmp_path / "file.txt", "alice")

    def test_handles_zero_paths(self, mocker, mock_chown: MagicMock):
        mocker.patch(f"{_MODULE}.is_root", return_value=True)

        UserContext(archcare_user="alice").chown_if_root()  # must not raise

        mock_chown.assert_not_called()


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


class TestImmutability:
    def test_archcare_user_cannot_be_reassigned(self):
        """
        frozen=True is deliberate: 'resolved once per run' is a real
        invariant this class exists to guarantee, not just a style choice.
        """
        context = UserContext(archcare_user="alice")

        with pytest.raises(FrozenInstanceError):
            context.archcare_user = "bob"  # ty:ignore[invalid-assignment]
