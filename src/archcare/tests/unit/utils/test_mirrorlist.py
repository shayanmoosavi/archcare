"""Unit tests for mirrorlist parsing and validation."""

from pathlib import Path

from archcare.utils.mirrorlist import get_mirrorlist_info, validate_mirrorlist

# ---------------------------------------------------------------------------
# validate_mirrorlist
# ---------------------------------------------------------------------------


class TestValidateMirrorlist:
    def test_returns_false_if_file_missing(self, tmp_path):
        is_valid, msg = validate_mirrorlist(tmp_path / "missing_mirrorlist")
        assert is_valid is False
        assert "does not exist" in msg

    def test_returns_false_if_file_empty(self, tmp_path):
        empty_file: Path = tmp_path / "empty"
        empty_file.touch()

        is_valid, msg = validate_mirrorlist(empty_file)
        assert is_valid is False
        assert "empty" in msg.lower()

    def test_returns_false_if_no_active_servers(self, tmp_path):
        no_servers: Path = tmp_path / "no_servers"
        no_servers.write_text("# Server = https://mirror.example.com\n# Just comments")

        is_valid, msg = validate_mirrorlist(no_servers)
        assert is_valid is False
        assert "No valid mirror" in msg

    def test_returns_true_for_valid_mirrorlist(self, tmp_path):
        valid_file: Path = tmp_path / "valid"
        valid_file.write_text(
            "Server = https://mirror1.com/$repo/os/$arch\n"
            "Server = http://mirror2.com/$repo/os/$arch\n"
        )

        is_valid, msg = validate_mirrorlist(valid_file)
        assert is_valid is True
        assert "2 mirrors" in msg


# ---------------------------------------------------------------------------
# get_mirrorlist_info
# ---------------------------------------------------------------------------


class TestGetMirrorlistInfo:
    def test_returns_defaults_if_missing(self, tmp_path):
        info = get_mirrorlist_info(tmp_path / "missing")
        assert info["total_mirrors"] == 0
        assert info["protocols"] == set()
        assert info["last_modified"] is None

    def test_extracts_protocols_and_counts(self, tmp_path):
        mirrorlist: Path = tmp_path / "mirrorlist"
        mirrorlist.write_text(
            "Server = https://mirror1.com\n"
            "Server = http://mirror2.com\n"
            "Server = rsync://mirror3.com\n"
            "# Server = ftp://ignored.com\n"
            "Server = https://mirror4.com\n"
        )

        info = get_mirrorlist_info(mirrorlist)

        assert info["total_mirrors"] == 4
        # Ensure protocols aren't duplicated
        assert info["protocols"] == {"https", "http", "rsync"}
        # Ensure timestamp was generated
        assert info["last_modified"] is not None
