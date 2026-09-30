"""
Recovery service for reading task recovery records.

Contains [`RecoveryService`][], the business logic behind `archcare task recover <task>`: it reads
the recovery record a task left behind and turns it into [`RecoveryResponse`][] — what can be
recovered, and the exact commands to recover it.

Every failure mode is a returned response, never an exception. A missing record, an unknown task
and malformed JSON are all *ordinary* states — the user may simply never have run the task — so
they are reported through `RecoveryResponse.reason` for the presenter to explain.

See Also:
    - [`archcare.services.responses`][]: Response DTOs returned by the services layer
    - [`archcare.cli.commands.task`][]: The `task recover` command delegating to this service
"""

import json
from pathlib import Path
from typing import Any

from archcare.config import AppSettings
from archcare.services.responses import RecoveryResponse
from archcare.utils.system_update import build_restore_script

# The package cache is where an uninstalled package is reinstalled from: see the ArchWiki page
# https://wiki.archlinux.org/title/Pacman#Cleaning_the_package_cache. The recovery manifest cannot
# supply the artifact path, so the command points at the directory.
_PACKAGE_CACHE_DIR = "/var/cache/pacman/pkg/"


class RecoveryService:
    """
    Reads task recovery records and turns them into ready-to-run guidance.

    A task that leaves recovery artifacts behind writes them to
    `settings.recovery_dir/<task-name>.json` (see
    [`SystemUpdateTask`][archcare.tasks.system_update.SystemUpdateTask]). This service reads that
    file and returns a [`RecoveryResponse`][] describing what can be recovered and the commands to
    do it.

    This service never executes a recovery command. Restoring a sync database or rolling back a
    snapshot is destructive and irreversible, and the decision to do it belongs to the user.

    Reading is read-only with one deliberate exception: when the record names a sync-database
    backup, the restore script is written next to the record and offered as a single command,
    so the user is not asked to hand-assemble a `pacman` transaction. The directory is still
    never created on its own — only that branch writes, and only when there is a backup to point
    the script at.

    See also:
        - [`RecoveryResponse`][]: The response this returns
        - [`render_recovery`][archcare.cli.presenters.task_presenter.TaskPresenter.render_recovery]:
            Renders the response
    """

    def __init__(self, settings: AppSettings) -> None:
        """
        Initialize the recovery service.

        Args:
            settings (AppSettings): Application settings, used only to resolve
                [`recovery_dir`][archcare.config.models.AppSettings.recovery_dir].
        """
        self._settings = settings

    def get_recovery_info(self, task_name: str) -> RecoveryResponse:
        """
        Load the recovery record for `task_name` and build recovery guidance.

        Args:
            task_name (str): Name of the task whose record to read.

        Returns:
            RecoveryResponse: `available=True` with the record's contents and the derived
                commands when the record exists and parses. Otherwise `available=False` with
                `reason` explaining why — a missing file, an unknown task, or malformed JSON
                are all reported, never raised, because all three are ordinary states rather
                than bugs.
        """
        record_path = self._settings.recovery_dir / f"{task_name}.json"
        if not record_path.exists():
            return RecoveryResponse(
                reason=f"No recovery record found for {task_name!r} at {record_path}."
            )
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
            return RecoveryResponse(reason=f"Recovery record for {task_name!r} is unreadable: {e}")

        return RecoveryResponse(
            available=True,
            updated_at=record.get("updated_at"),
            snapshot_id=record.get("pre_update_snapshot_id"),
            sync_db_backup=record.get("sync_db_backup"),
            manifest_before=record.get("manifest_before"),
            manifest_after=record.get("manifest_after"),
            packages_removed=list(record.get("packages_removed", [])),
            aur_packages_failed=list(record.get("aur_packages_failed", [])),
            commands=self._build_commands(record),
        )

    def _build_commands(self, record: dict[str, Any]) -> tuple[str, ...]:
        """
        Derive recovery commands from a record, most-relevant first.

        Each command is emitted only when the record actually supports it, so a run on a
        machine without snapper does not print a `snapper rollback` the user cannot run.

        Args:
            record (dict[str, Any]): The parsed recovery record.

        Returns:
            tuple[str, ...]: Commands to print, in the order they should be attempted.
        """
        commands: list[str] = []
        snapshot_id = record.get("pre_update_snapshot_id")
        if isinstance(snapshot_id, int):
            commands.append(f"snapper rollback {snapshot_id}")
        backup = record.get("sync_db_backup")
        if backup:
            # Write the restore script and point the user at it.
            script = self._write_restore_script(Path(str(backup)))
            commands.append(f"bash {script}   # restores the pre-upgrade state; read it first")
        if record.get("packages_removed"):
            # NOT `elif`. The restore script reinstalls what `pacman -Q?` currently lists, and
            # that is the *installed* set — a package this run removed is in none of those
            # queries, so the script provably cannot bring it back. The cache pointer is the
            # only guidance that covers that case, and it is the reason
            # `cache_keep_uninstalled_versions` defaults to 1.
            #
            # The manifest records that a package existed as `name version`, not which artifact
            # is on disk, so no correct `pacman -U` command is derivable from it.
            commands.append(f"ls {_PACKAGE_CACHE_DIR}  # reinstall a removed package from here")
            commands.append("# Example installation command:")
            commands.append(f"sudo pacman -U {_PACKAGE_CACHE_DIR}[package-name].pkg.tar.zst")
        return tuple(commands)

    def _write_restore_script(self, sync_db_backup: Path) -> Path:
        """
        Write the restore script next to the recovery record, once.

        Deliberately NOT regenerated: the user is expected to read it and may have edited it, or
        run part of it. Overwriting it on a second `recover` call would discard that.

        Args:
            sync_db_backup (Path): Sync-database backup recorded in the recovery record. The
                script treats a missing backup as critical, so this is the one input it needs.

        Returns:
            Path: Path to the script, whether newly written or already present.
        """
        path = self._settings.recovery_dir / "downgrade.sh"
        if path.exists():
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(build_restore_script(sync_db_backup), encoding="utf-8")
        path.chmod(0o755)
        return path
