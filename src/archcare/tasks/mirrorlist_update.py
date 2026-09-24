"""
Mirrorlist update task implementation for Archcare.

This module provides `MirrorlistUpdateTask`, a maintenance task that refreshes the pacman mirrorlist
using [reflector](https://wiki.archlinux.org/title/Reflector). It is registered in the static task
registry and exposed to users as the `mirrorlist-update` command.

Workflow:
    1. `pre_check()` verifies that `reflector` is installed and the configured mirrorlist
        file exists.
    2. `execute()` snapshots the current mirrorlist metadata, creates a timestamped backup, runs
        `reflector` with the parameters from
        [`MirrorlistSettings`][archcare.config.models.MirrorlistSettings] (country, protocol,
        recency, mirror count, sort order), validates the resulting mirrorlist, and records
        before/after metrics in a [`MirrorlistUpdateDetails`][] payload.
    3. If anything goes wrong (reflector failure or invalid output), the raised exception triggers
        [`BaseTask.rollback`][], which restores the mirrorlist from the backup.
    4. `post_execute()` prunes old backups after a successful update, keeping only the
        `backup_retention_count` (default: 5) most recent.

!!! warning "Destructive operation"
    This task overwrites `/etc/pacman.d/mirrorlist` (or the configured path). The automatic
    backup/rollback mechanism is the safety net — if the rollback itself fails, the task logs
    the backup location for manual restoration.

See Also:
    - [`BaseTask`][]: Abstract workflow this task implements
    - [`TaskResult`][]: The structured result object that the task returns
    - [`MirrorlistUpdateDetails`][]: Details schema produced by this task
    - [`archcare.utils.mirrorlist`][]: Mirrorlist parsing and reflector invocation utilities
"""

from pathlib import Path
from typing import Any

from loguru import logger

from archcare.core import BaseTask, MirrorlistUpdateDetails, TaskResult, failed, success
from archcare.utils import (
    backup_file,
    check_command_exists,
    get_mirrorlist_info,
    restore_backup,
    update_mirrorlist,
    validate_mirrorlist,
)
from archcare.utils.mirrorlist import ReflectorArgs


class MirrorlistUpdateTask(BaseTask):
    """
    Update the pacman mirrorlist using `reflector` with backup/rollback safety.

    The task backs up the current mirrorlist, regenerates it with the fastest mirrors according to
    [`MirrorlistSettings`][archcare.config.models.MirrorlistSettings], validates the new file, and
    rolls back to the backup if validation or the update itself fails.

    This task follows the [`BaseTask`][] Template Method contract:

    - `pre_check()`: requires `reflector` in `PATH` and an existing mirrorlist file
    - `execute()`: backup → reflector → validate → report
    - `post_execute()`: cleanup of old backups on success
    - `rollback()`: restore from backup (invoked automatically by `BaseTask.run()`
        when `execute()` raises)

    Attributes:
        backup_path (Path | None): Path to the timestamped backup created during
            `execute()`. May be pre-set via the constructor (useful for tests);
            otherwise `None` until a backup is created. Consumed by
            `rollback()` and `post_execute()`.
        mirrorlist_path (Path): Absolute path of the mirrorlist file being
            managed, taken from
            [`MirrorlistSettings.path`][archcare.config.models.MirrorlistSettings].
    """

    def __init__(self, backup_path: Path | None = None, *args, **kwargs):
        """
        Initialize the mirrorlist update task.

        Args:
            backup_path (Path | None): Optional pre-existing backup path to use instead of creating
                a new one. Primarily useful for testing rollback behavior. Defaults to `None` (a
                fresh timestamped backup is created in `execute()`).

        Other Args:
            *args (tuple): Forwarded to `BaseTask.__init__()` (`config`, `settings`, etc.).
            **kwargs (dict): Forwarded to `BaseTask.__init__()`.

        Side Effects:
            Resolves `self.mirrorlist_path` from `self.settings.mirrorlist.path`.
        """
        super().__init__(*args, **kwargs)
        self.backup_path: Path | None = backup_path
        self.mirrorlist_path = self.settings.mirrorlist.path

    def pre_check(self) -> tuple[bool, str]:
        """
        Verify prerequisites for the mirrorlist update.

        Checks that `reflector` is installed and that the configured mirrorlist file exists (it is
        needed for the backup step).

        Returns:
            (tuple[bool, str]): A tuple of:

                - `can_run` (`bool`): `True` if all prerequisites are satisfied, `False` otherwise.
                - `reason` (`str`): Explanation when a prerequisite fails — including the
                    `sudo pacman -S reflector` install hint or the missing file path (empty string
                    on success).
        """
        # Check if reflector is installed
        if not check_command_exists("reflector"):
            return False, ("reflector is not installed. Install with: sudo pacman -S reflector")

        # Check if mirrorlist file exists
        if not self.mirrorlist_path.exists():
            return False, f"Mirrorlist file not found: {self.mirrorlist_path}"

        return True, ""

    def execute(self) -> TaskResult[MirrorlistUpdateDetails]:
        """
        Update the mirrorlist with the fastest mirrors.

        Process:
            1. Snapshot current mirrorlist metadata (mirror count, protocols, last modified) via
                [`get_mirrorlist_info`][].
            2. Create a timestamped backup of the mirrorlist. If the backup fails, return a
                `FAILURE` result immediately (no update is attempted without a safety net).
            3. Run `reflector` with parameters from
                [`MirrorlistSettings`][archcare.config.models.MirrorlistSettings] (`country`,
                `protocol`, `latest`, `number`, `sort`) while showing a progress spinner.
            4. Validate the new mirrorlist. A `RuntimeError` is raised on reflector failure or
                invalid output, which triggers automatic `rollback()` from `BaseTask.run()`.
            5. Snapshot the new mirrorlist metadata and return a `SUCCESS` result with before/after
                metrics.

        Returns:
            (TaskResult[MirrorlistUpdateDetails]):
                Result whose `details` is a `MirrorlistUpdateDetails`:

                - `success` with `old_mirrors`/`new_mirrors` counts, parsed `old_info`/`new_info`
                    metadata, and the `backup_path`.
                - `failed` (with `old_info` only) if the backup could not be created.

        Raises:
            RuntimeError: If `reflector` fails or the new mirrorlist fails validation. Caught by
                `BaseTask.run()`, which invokes `rollback()` and records the task as failed.

        Side Effects:
            - Creates a backup file next to the mirrorlist.
            - Overwrites the mirrorlist file via `reflector`.
            - Emits Loguru log messages at `debug`/`info`/`error` levels.
            - Drives the injected progress reporter (spinner around reflector).
        """
        logger.info("Starting mirrorlist update")

        # Get current mirrorlist info
        logger.debug("Getting current mirrorlist info")
        old_info = get_mirrorlist_info(self.mirrorlist_path)
        logger.info(
            f"Current mirrorlist: {old_info.total_mirrors} mirrors, "
            f"last modified: {old_info.last_modified}"
        )

        # Create backup
        try:
            logger.info("Creating backup of current mirrorlist")
            self.backup_path = backup_file(self.mirrorlist_path)
            logger.debug(f"Backup created: {self.backup_path}")
        except Exception as e:
            logger.error(f"Failed to create backup: {e}")
            return failed(
                f"Failed to create mirrorlist backup: {e}",
                error=str(e),
                details=MirrorlistUpdateDetails(old_info=old_info),
            )

        # Run reflector
        try:
            mirrorlist_settings = self.settings.mirrorlist
            reflector_args: dict[str, Any] = {
                "country": mirrorlist_settings.country,
                "protocol": mirrorlist_settings.protocol,
                "latest": mirrorlist_settings.latest,
                "number": mirrorlist_settings.number_of_mirrors,
                "sort": mirrorlist_settings.sort,
                "save_path": self.mirrorlist_path,
            }

            logger.info("Running reflector to update mirrorlist")
            logger.debug(f"Parameters: {reflector_args}")

            with self.progress.spinner("Running reflector to find fastest mirrors..."):
                result = update_mirrorlist(ReflectorArgs(**reflector_args))

            if not result.success:
                logger.error(f"Reflector failed: {result.stderr}")
                raise RuntimeError(f"Reflector failed: {result.stderr}")

            logger.info("Reflector completed successfully")

        except Exception as e:
            logger.error(f"Failed to run reflector: {e}")
            raise

        # Validate new mirrorlist
        logger.info("Validating new mirrorlist")
        is_valid, validation_msg = validate_mirrorlist(self.mirrorlist_path)

        if not is_valid:
            logger.error(f"Validation failed: {validation_msg}")
            raise RuntimeError(f"New mirrorlist validation failed: {validation_msg}")

        logger.info(f"Validation passed: {validation_msg}")

        # Get new mirrorlist info
        new_info = get_mirrorlist_info(self.mirrorlist_path)
        logger.info(f"New mirrorlist: {new_info.total_mirrors} mirrors")

        return success(
            f"Mirrorlist updated successfully with {new_info.total_mirrors} mirrors",
            details=MirrorlistUpdateDetails(
                old_mirrors=old_info.total_mirrors,
                new_mirrors=new_info.total_mirrors,
                old_info=old_info,
                new_info=new_info,
                backup_path=str(self.backup_path),
            ),
        )

    def post_execute(self, result: TaskResult[MirrorlistUpdateDetails]) -> None:
        """
        Clean up old mirrorlist backups after a successful update.

        Keeps only the `backup_retention_count` (default: 5) most recent `mirrorlist_*.backup` files
        in the backup directory (determined by file modification time) and deletes the rest. No-op
        when the update failed or no backup exists.

        Args:
            result (TaskResult[MirrorlistUpdateDetails]): The result produced by `execute()`.

        Side Effects:
            - Deletes old backup files from disk.
            - Emits Loguru log messages at `debug`/`info`/`error` levels;
                cleanup failures are logged but never propagate.
        """
        if result.is_success() and self.backup_path:
            try:
                logger.info("Cleaning up old mirrorlist backups")
                backup_dir = self.backup_path.parent
                backups = sorted(
                    backup_dir.glob("mirrorlist_*.backup"),
                    key=lambda p: p.stat().st_mtime,
                )
                # Keep only the N most recent backups
                retention = self.settings.mirrorlist.backup_retention_count
                if len(backups) >= retention:
                    for old_backup in backups[:-retention]:
                        logger.debug(f"Removing old backup: {old_backup}")
                        old_backup.unlink()
                    logger.info("Old backups cleanup completed")
                else:
                    logger.info(f"Less than {retention} backups present, no cleanup needed")
            except Exception as e:
                logger.error(f"Failed to cleanup old backups: {e}")

    def rollback(self) -> None:
        """
        Restore the mirrorlist from the backup if the update fails.

        Invoked automatically by [`BaseTask.run`][] when `execute()` raises (e.g., reflector failure
        or failed validation). If the restoration itself fails, logs a `critical` message pointing
        at the backup so the user can restore manually.

        Side Effects:
            - Overwrites the mirrorlist file with the backup contents (when a backup exists).
            - Emits Loguru log messages at `warning`/`info`/`error`/`critical` levels.
        """
        if self.backup_path and self.backup_path.exists():
            try:
                logger.warning("Rolling back to previous mirrorlist")
                restore_backup(self.backup_path, self.mirrorlist_path)
                logger.info("Rollback completed successfully")
            except Exception as e:
                logger.error(f"Rollback failed: {e}")
                logger.critical(
                    f"Mirrorlist may be broken! Manually restore from: {self.backup_path}"
                )
        else:
            logger.warning("No backup available for rollback")
