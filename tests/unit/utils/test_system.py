"""Unit tests for system utility parsing and formatting logic."""

from datetime import datetime, timedelta
from pathlib import Path
from subprocess import CalledProcessError, TimeoutExpired
from unittest.mock import MagicMock

import pytest

from archcare.utils.system import (
    _VALID_UNIT_SUFFIXES,
    CommandResult,
    _get_boot_time,
    _get_service_description,
    _parse_active_status,
    _parse_loaded_status,
    _parse_main_pid,
    change_ownership_to_user,
    check_filesystem_errors,
    format_bytes,
    get_system_uptime,
    get_systemd_failed_services,
    is_valid_systemd_unit_name,
    run_command,
    run_command_with_sudo,
)

_MODULE = "archcare.utils.system"

_PATCH_SUBPROCESS_RUN = f"{_MODULE}.subprocess.run"
_PATCH_IS_ROOT = f"{_MODULE}.is_root"
_PATCH_RUN_COMMAND = f"{_MODULE}.run_command"
_PATCH_RUN_SYSTEMCTL = f"{_MODULE}.run_systemctl"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def target_file(tmp_path) -> Path:
    target: Path = tmp_path / "target_file"
    target.touch()
    return target


@pytest.fixture
def mock_run_command(mocker) -> MagicMock:
    return mocker.patch(_PATCH_RUN_COMMAND)


# ---------------------------------------------------------------------------
# systemctl status parsing
# ---------------------------------------------------------------------------


class TestSystemctlParsing:
    def test_parse_loaded_status(self):
        # Service is loaded properly
        assert (
            _parse_loaded_status(
                "   Loaded: loaded (/usr/lib/systemd/system/dbus-broker.service;"
                " disabled; preset: disabled)"
            )
            is True
        )
        # Service is missing
        assert _parse_loaded_status("Unit nonexistent.service could not be found.") is False

    def test_parse_active_status_running(self):
        state, is_running = _parse_active_status(
            "   Active: active (running) since Mon 2026-06-26"
        )
        assert state == "active"
        assert is_running is True

    def test_parse_active_status_exited(self):
        # e.g., oneshot services
        state, is_running = _parse_active_status(
            "   Active: active (exited) since Mon 2026-06-26"
        )
        assert state == "active"
        assert is_running is False

    def test_parse_active_status_inactive(self):
        state, is_running = _parse_active_status("   Active: inactive (dead)")
        assert state == "inactive"
        assert is_running is False

    def test_parse_active_status_failed(self):
        state, is_running = _parse_active_status("   Active: failed (Result: exit-code)")
        assert state == "failed"
        assert is_running is False

    def test_parse_active_status_unknown(self):
        state, is_running = _parse_active_status("   Active: something entirely unexpected")
        assert state == "unknown"
        assert is_running is False

    def test_parse_main_pid_valid(self):
        assert _parse_main_pid(" Main PID: 1234 (code=exited, status=0/SUCCESS)") == 1234

    def test_parse_main_pid_invalid_or_missing(self):
        assert _parse_main_pid(" Main PID: unknown") is None
        assert _parse_main_pid(" Main PID:") is None
        assert _parse_main_pid("Some other line entirely") is None

    @pytest.mark.parametrize(
        "svc_name,out,desc",
        [
            (
                "acpid.service",
                "acpid.service loaded active running ACPI event daemon",
                "ACPI event daemon",
            ),
            (
                "systemd-random-seed.service",
                "systemd-random-seed.service loaded active exited Load/Save OS Random Seed",
                "Load/Save OS Random Seed",
            ),
            (
                "service-with-no-desc.service",
                "service-with-no-desc.service loaded active exited ",
                "",
            ),
        ],
    )
    def test_get_service_description_correctly_parses_found_service(
        self, svc_name, out, desc, mocker
    ):
        mocker.patch(
            f"{_MODULE}.run_systemctl",
            return_value=CommandResult(
                command="",
                returncode=0,
                stdout=out,
                stderr="",
                success=True,
            ),
        )
        assert _get_service_description(svc_name) == desc

    def test_get_service_description_correctly_parses_not_found_service(self, mocker):
        mocker.patch(
            f"{_MODULE}.run_systemctl",
            return_value=CommandResult(
                command="",
                returncode=0,
                stdout="",
                stderr="",
                success=True,
            ),
        )
        assert _get_service_description("nonexistent.service") == ""

    def test_get_service_description_returns_empty_when_command_fails(self, mocker):
        mocker.patch(
            f"{_MODULE}.run_systemctl",
            return_value=CommandResult(
                command="",
                returncode=1,
                stdout="some.service loaded active running Some description",
                stderr="unit not found",
                success=False,
            ),
        )
        assert _get_service_description("some.service") == ""


# ---------------------------------------------------------------------------
# Boot time
# ---------------------------------------------------------------------------


class TestGetBootTime:
    def test_falls_back_to_now_on_psutil_failure(self, mocker):
        """
        Every other test mocks _get_boot_time() itself, so its own
        try/except around psutil.boot_time() has no coverage elsewhere.
        """
        mocker.patch("psutil.boot_time", side_effect=Exception("no /proc/stat"))
        before = datetime.now()
        result = _get_boot_time()
        after = datetime.now()

        assert before <= result <= after


# ---------------------------------------------------------------------------
# Formatting and Calculations
# ---------------------------------------------------------------------------


class TestFormatting:
    @pytest.mark.parametrize(
        "bytes_val,bytes_expected",
        [
            (500, "500.00 B"),
            (1024, "1.00 KB"),
            (1024**2 * 1.5, "1.50 MB"),
            (1024**3 * 2.75, "2.75 GB"),
            (1024**4 * 3.1, "3.10 TB"),
            (1024**5 * 3.5, "3.50 PB"),
        ],
    )
    def test_format_bytes_scales_correctly(self, bytes_val, bytes_expected):
        assert format_bytes(bytes_val) == bytes_expected

    @pytest.mark.parametrize(
        "expected,uptime",
        [
            ("just now", timedelta(seconds=30)),  # Test just now (less than a minute)
            (
                "45 minutes",
                timedelta(minutes=45),
            ),  # Test minutes only (less than an hour)
            (
                "3 hours, 15 minutes",
                timedelta(hours=3, minutes=15),
            ),  # Test hours and minutes
            (
                "2 days, 5 hours",
                timedelta(days=2, hours=5, minutes=30),
            ),  # Test days and hours (minutes should be hidden when days > 0)
            ("1 day, 1 hour", timedelta(days=1, hours=1)),  # Test singular phrasing
        ],
    )
    def test_uptime_formatting(self, expected, uptime, mocker):
        frozen_boot = datetime(2026, 6, 20, 12, 0, 0)
        mocker.patch(f"{_MODULE}._get_boot_time", return_value=frozen_boot)
        mock_datetime: MagicMock = mocker.patch(f"{_MODULE}.datetime")

        mock_datetime.now.return_value = frozen_boot + uptime
        assert get_system_uptime() == expected


# ---------------------------------------------------------------------------
# run_command
# ---------------------------------------------------------------------------


class TestRunCommand:
    """
    Real subprocess calls for POSIX-guaranteed commands (echo/false/sleep) -
    these exercise real subprocess.CompletedProcess -> CommandResult
    construction.
    """

    def test_list_command_returns_success_result(self):
        result = run_command(["echo", "hello"])
        assert result.success is True
        assert result.returncode == 0
        assert result.stdout == "hello"

    def test_string_command_is_split_and_run(self):
        """.split() is a naive whitespace split, not shlex - fine for
        simple commands with no quoted arguments."""
        result = run_command("echo hello")
        assert result.success is True
        assert result.returncode == 0
        assert result.stdout == "hello"

    def test_non_zero_exit_without_check_returns_failure_result(self):
        result = run_command(["false"])
        assert result.success is False
        assert result.returncode == 1

    def test_check_true_raises_called_process_error_for_real(self):
        """
        Using a real failing command (rather than mocking subprocess.run)
        proves run_command's except-and-reraise doesn't accidentally
        swallow the exception subprocess.run raises on its own.
        """
        with pytest.raises(CalledProcessError):
            run_command(["false"], check=True)

    def test_timeout_raises_timeout_expired_for_real(self):
        with pytest.raises(TimeoutExpired):
            run_command(["sleep", "2"], timeout=0.01)

    def test_systemctl_exit_code_3_counts_as_success(self, mocker):
        """
        systemctl status returns 3 for a failed-but-loaded service - that's
        treated as a successful *check*, not a failed command. Mocked
        because reproducing a real failed unit deterministically isn't
        portable, and some CI environments don't run systemd at all.
        """
        mocker.patch(
            _PATCH_SUBPROCESS_RUN,
            return_value=MagicMock(returncode=3, stdout="", stderr=""),
        )
        result = run_command(["systemctl", "status", "some.service"])
        assert result.success is True

    def test_non_systemctl_exit_code_3_is_a_failure(self, mocker):
        """
        Contrast case: the same returncode=3 is an ordinary failure for
        any command whose string doesn't contain 'systemctl' - pins down
        that the substring check, not the exit code itself, drives the
        special case above.
        """
        mocker.patch(
            _PATCH_SUBPROCESS_RUN,
            return_value=MagicMock(returncode=3, stdout="", stderr=""),
        )

        result = run_command(["some-other-command"])
        assert result.success is False

    def test_strips_whitespace_from_stdout_and_stderr(self, mocker):
        mocker.patch(
            _PATCH_SUBPROCESS_RUN,
            return_value=MagicMock(returncode=0, stdout="  hello  \n", stderr=" world \n"),
        )
        result = run_command(["some-command"])

        assert result.stdout == "hello"
        assert result.stderr == "world"


# ---------------------------------------------------------------------------
# run_command_with_sudo
# ---------------------------------------------------------------------------


class TestRunCommandWithSudo:
    """
    run_command itself is already covered above, so here we only mock it
    and verify run_command_with_sudo's own logic: whether 'sudo' gets
    prepended, and that kwargs are forwarded unchanged.
    """

    def test_prepends_sudo_when_not_root(self, mocker, mock_run_command: MagicMock):
        mocker.patch(_PATCH_IS_ROOT, return_value=False)
        run_command_with_sudo(["pacman", "-Syu"])

        assert mock_run_command.call_args.args[0] == [
            "sudo",
            "pacman",
            "-Syu",
        ]

    def test_does_not_prepend_sudo_when_already_root(
        self, mocker, mock_run_command: MagicMock
    ):
        mocker.patch(_PATCH_IS_ROOT, return_value=True)
        run_command_with_sudo(["pacman", "-Syu"])

        assert mock_run_command.call_args.args[0] == ["pacman", "-Syu"]

    def test_string_command_is_converted_before_sudo_prefix(
        self, mocker, mock_run_command: MagicMock
    ):
        mocker.patch(_PATCH_IS_ROOT, return_value=False)
        run_command_with_sudo("pacman -Syu")

        assert mock_run_command.call_args.args[0] == [
            "sudo",
            "pacman",
            "-Syu",
        ]

    def test_forwards_kwargs_to_run_command(self, mocker, mock_run_command: MagicMock):
        mocker.patch(_PATCH_IS_ROOT, return_value=True)
        run_command_with_sudo(["pacman", "-Syu"], check=True, timeout=15)
        assert mock_run_command.call_args.kwargs["check"] is True
        assert mock_run_command.call_args.kwargs["timeout"] == 15


# ---------------------------------------------------------------------------
# get_systemd_failed_services
# ---------------------------------------------------------------------------


class TestGetSystemdFailedServices:
    def test_returns_empty_list_when_systemctl_fails(self, mocker):
        mocker.patch(
            _PATCH_RUN_SYSTEMCTL,
            return_value=CommandResult(
                command="", returncode=1, stdout="", stderr="", success=False
            ),
        )
        assert get_systemd_failed_services() == []

    def test_parses_unit_names_from_output(self, mocker):
        stdout = (
            "nginx.service     loaded failed failed nginx web server\n"
            "docker.service    loaded failed failed Docker daemon\n"
        )
        mocker.patch(
            _PATCH_RUN_SYSTEMCTL,
            return_value=CommandResult(
                command="", returncode=0, stdout=stdout, stderr="", success=True
            ),
        )

        result = get_systemd_failed_services()
        assert result == ["nginx.service", "docker.service"]

    def test_skips_blank_lines(self, mocker):
        stdout = "nginx.service loaded failed failed nginx\n\n   \n"
        mocker.patch(
            _PATCH_RUN_SYSTEMCTL,
            return_value=CommandResult(
                command="", returncode=0, stdout=stdout, stderr="", success=True
            ),
        )
        result = get_systemd_failed_services()
        assert result == ["nginx.service"]


# ---------------------------------------------------------------------------
# check_filesystem_errors
# ---------------------------------------------------------------------------


class TestCheckFilesystemErrors:
    def test_returns_empty_list_when_command_fails(self, mocker):
        mocker.patch(
            _PATCH_RUN_COMMAND,
            return_value=CommandResult(
                command="", returncode=1, stdout="", stderr="", success=False
            ),
        )
        assert check_filesystem_errors() == []

    def test_returns_empty_list_when_stdout_empty(self, mocker):
        mocker.patch(
            _PATCH_RUN_COMMAND,
            return_value=CommandResult(
                command="", returncode=0, stdout="", stderr="", success=True
            ),
        )
        assert check_filesystem_errors() == []

    def test_filters_lines_by_keyword(self, mocker):
        stdout = (
            "kernel: random unrelated message\n"
            "kernel: EXT4-fs error on device sda1\n"
            "kernel: another unrelated line\n"
            "kernel: I/O error on device sdb\n"
        )
        mocker.patch(
            _PATCH_RUN_COMMAND,
            return_value=CommandResult(
                command="", returncode=0, stdout=stdout, stderr="", success=True
            ),
        )

        result = check_filesystem_errors()
        assert len(result) == 2
        assert all("unrelated" not in line for line in result)

    def test_limits_to_last_10_errors(self, mocker):
        """
        Pins down errors[-10:] specifically - feeding 12 matching lines
        must return the *last* 10, not the first 10, since an off-by-one
        or wrong-end slice would silently drop the most recent errors.
        """
        lines = [f"kernel: disk error #{i}" for i in range(12)]
        stdout = "\n".join(lines)
        mocker.patch(
            _PATCH_RUN_COMMAND,
            return_value=CommandResult(
                command="", returncode=0, stdout=stdout, stderr="", success=True
            ),
        )
        result = check_filesystem_errors()
        assert len(result) == 10
        assert result[0] == "kernel: disk error #2"
        assert result[-1] == "kernel: disk error #11"


# ---------------------------------------------------------------------------
# change_ownership_to_user
# ---------------------------------------------------------------------------


class TestChangeOwnershipToUser:
    def test_changes_ownership_for_valid_user(self, target_file: Path, mocker):
        mocker.patch("pwd.getpwnam", return_value=MagicMock(pw_uid=1000, pw_gid=1000))
        mock_chown: MagicMock = mocker.patch("os.chown")
        change_ownership_to_user(target_file, "alice")

        mock_chown.assert_called_once_with(target_file, 1000, 1000)

    def test_unknown_user_does_not_raise(self, target_file: Path, mocker):
        mocker.patch("pwd.getpwnam", side_effect=KeyError("no such user"))
        mock_chown: MagicMock = mocker.patch("os.chown")
        change_ownership_to_user(target_file, "nonexistent")  # Must not raise

        mock_chown.assert_not_called()

    def test_permission_error_does_not_raise(self, target_file: Path, mocker):
        mocker.patch("pwd.getpwnam", return_value=MagicMock(pw_uid=1000, pw_gid=1000))
        mock_chown: MagicMock = mocker.patch(
            "os.chown", side_effect=PermissionError("Permission denied")
        )
        change_ownership_to_user(target_file, "alice")  # Must not raise

        mock_chown.assert_called_once_with(target_file, 1000, 1000)

    def test_unexpected_error_does_not_raise(self, target_file: Path, mocker):
        mocker.patch("pwd.getpwnam", return_value=MagicMock(pw_uid=1000, pw_gid=1000))
        mock_chown: MagicMock = mocker.patch("os.chown", side_effect=OSError("disk full"))
        change_ownership_to_user(target_file, "alice")  # Must not raise

        mock_chown.assert_called_once_with(target_file, 1000, 1000)


# ---------------------------------------------------------------------------
# is_valid_systemd_unit_name
# ---------------------------------------------------------------------------


class TestIsValidSystemdUnitName:
    def test_simple_valid_name(self):
        assert is_valid_systemd_unit_name("my-service.service")

    def test_empty_string_is_invalid(self):
        assert not is_valid_systemd_unit_name("")

    def test_having_no_suffix_is_invalid(self):
        assert not is_valid_systemd_unit_name("my-service")

    def test_exceeding_char_limit_is_invalid(self):
        assert not is_valid_systemd_unit_name("a" * 256 + ".service")

    @pytest.mark.parametrize("suffix", _VALID_UNIT_SUFFIXES)
    def test_valid_suffix(self, suffix: str):
        assert is_valid_systemd_unit_name(f"my-service.{suffix}")

    def test_having_multiple_dots_is_allowed(self):
        assert is_valid_systemd_unit_name("org.freedesktop.NetworkManager.service")

    @pytest.mark.parametrize(
        "invalid",
        [
            ".service",  # Empty base name
            "@.service",  # Empty template name
            "my-service@.service",  # Empty instance name
        ],
    )
    def test_empty_section_names_are_invalid(self, invalid: str):
        assert not is_valid_systemd_unit_name(invalid)

    def test_template_unit_instances_are_allowed(self):
        assert is_valid_systemd_unit_name("my-service@instance.service")

    @pytest.mark.parametrize(
        "invalid",
        [
            "my&invalid/-service@instance.service",  # Invalid chars in base name
            "my-service@invalid&.service",  # Invalid chars in instance name
            "my&invalid.service",  # Invalid chars in simple name
        ],
    )
    def test_invalid_chars_are_invalid(self, invalid: str):
        assert not is_valid_systemd_unit_name(invalid)
