"""Unit tests for NotificationManager's target-user dispatch behavior.

Desktop notifications from root-launched runs (systemd timers, `sudo`) must reach the
user's session bus *as its owning user*: the default D-Bus session policy rejects other
peer uids — root included — with `Error sending data: Broken pipe`. See
`NotificationManager._build_send_prefix` for the full mechanism.
"""

from unittest.mock import MagicMock

from archcare.core.notifications import NotificationManager, NotificationPayload

_MODULE = "archcare.core.notifications"
_PATCH_RUN_COMMAND = f"{_MODULE}.run_command"
_PATCH_CHECK_EXISTS = f"{_MODULE}.check_command_exists"


def _manager(mocker, target_user: str | None = None) -> tuple[NotificationManager, MagicMock]:
    mocker.patch(_PATCH_CHECK_EXISTS, return_value=True)
    manager = NotificationManager(target_user) if target_user else NotificationManager()
    run_command = mocker.patch(_PATCH_RUN_COMMAND)
    return manager, run_command


class TestTargetUserDispatch:
    def test_direct_send_without_target_user(self, mocker):
        manager, run_command = _manager(mocker)
        mocker.patch("os.geteuid", return_value=0)

        manager.send_notification(NotificationPayload(title="Title", message="body"))

        cmd = run_command.call_args.args[0]
        assert cmd[0] == "notify-send"
        assert "Title" in cmd

    def test_direct_send_as_non_root(self, mocker):
        manager, run_command = _manager(mocker, target_user="alice")
        mocker.patch("os.geteuid", return_value=1234)

        manager.send_notification(NotificationPayload(title="Title", message="body"))

        cmd = run_command.call_args.args[0]
        assert cmd[0] == "notify-send"

    def test_wraps_notify_send_as_target_user_for_root(self, mocker):
        manager, run_command = _manager(mocker, target_user="alice")
        mocker.patch("os.geteuid", return_value=0)
        mocker.patch("pwd.getpwnam", return_value=MagicMock(pw_uid=1234))

        manager.send_notification(NotificationPayload(title="Title", message="body"))

        cmd = run_command.call_args.args[0]
        assert cmd[:7] == [
            "runuser",
            "--user",
            "alice",
            "--",
            "env",
            "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1234/bus",
            "XDG_RUNTIME_DIR=/run/user/1234",
        ]
        assert cmd[7] == "notify-send"
        assert "Title" in cmd

    def test_unresolvable_target_user_falls_back_to_direct_send(self, mocker):
        manager, run_command = _manager(mocker, target_user="ghost")
        mocker.patch("os.geteuid", return_value=0)
        mocker.patch("pwd.getpwnam", side_effect=KeyError("ghost"))

        manager.send_notification(NotificationPayload(title="Title", message="body"))

        cmd = run_command.call_args.args[0]
        assert cmd[0] == "notify-send"
