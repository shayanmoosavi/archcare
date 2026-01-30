"""
Mirrorlist update task implementation for archcare.
"""

from pathlib import Path
from typing import Any

from loguru import logger

from archcare.core.models import TaskResult, failed, success
from archcare.tasks import BaseTask
from archcare.utils import (
    backup_file,
    check_command_exists,
    get_mirrorlist_info,
    restore_backup,
    update_mirrorlist,
    validate_mirrorlist,
)


class MirrorlistUpdateTask(BaseTask):
    """
    Update pacman mirrorlist using reflector.

    This task:
    - Backs up current mirrorlist
    - Updates mirrorlist with the fastest mirrors
    - Validates new mirrorlist
    - Rolls back if validation fails
    """

    def __init__(self, backup_path: Path | None = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.backup_path: Path | None = backup_path
        self.mirrorlist_path = self.settings.mirrorlist.path

    def pre_check(self) -> tuple[bool, str]:
        """
        Verify prerequisites for mirrorlist update.

        Returns:
            (can_run, reason) tuple
        """
        # Check if reflector is installed
        if not check_command_exists("reflector"):
            return False, (
                "reflector is not installed. " "Install with: sudo pacman -S reflector"
            )

        # Check if mirrorlist file exists
        if not self.mirrorlist_path.exists():
            return False, f"Mirrorlist file not found: {self.mirrorlist_path}"

        return True, ""

    def execute(self) -> TaskResult:
        """
        Update mirrorlist with the fastest mirrors.

        Returns:
            TaskResult with update details

        Process:
        1. Get current mirrorlist info
        2. Create backup
        3. Run reflector to update
        4. Validate new mirrorlist
        5. Rollback if validation fails
        """
        logger.info("Starting mirrorlist update")

        # Get current mirrorlist info
        logger.debug("Getting current mirrorlist info")
        old_info = get_mirrorlist_info(self.mirrorlist_path)
        logger.info(
            f"Current mirrorlist: {old_info['total_mirrors']} mirrors, "
            f"last modified: {old_info['last_modified']}"
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
                error=e,
                old_info=old_info,
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

            result = update_mirrorlist(**reflector_args)

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
        logger.info(f"New mirrorlist: {new_info['total_mirrors']} mirrors")

        return success(
            f"Mirrorlist updated successfully with {new_info['total_mirrors']} mirrors",
            old_mirrors=old_info["total_mirrors"],
            new_mirrors=new_info["total_mirrors"],
            old_info=old_info,
            new_info=new_info,
            backup_path=str(self.backup_path),
        )

    def post_execute(self, result: TaskResult):
        """Cleanup 5 oldest backups after successful update."""
        if result.is_success() and self.backup_path:
            try:
                logger.info("Cleaning up old mirrorlist backups")
                backup_dir = self.backup_path.parent
                backups = sorted(
                    backup_dir.glob("mirrorlist.*.backup"),
                    key=lambda p: p.stat().st_mtime,
                )
                # Keep only the 5 most recent backups
                if len(backups) >= 5:
                    for old_backup in backups[:-5]:
                        logger.debug(f"Removing old backup: {old_backup}")
                        old_backup.unlink()
                    logger.info("Old backups cleanup completed")
                else:
                    logger.info("Less than 5 backups present, no cleanup needed")
            except Exception as e:
                logger.error(f"Failed to cleanup old backups: {e}")

    def rollback(self):
        """
        Restore mirrorlist from backup if update fails.
        """
        if self.backup_path and self.backup_path.exists():
            try:
                logger.warning("Rolling back to previous mirrorlist")
                restore_backup(self.backup_path, self.mirrorlist_path)
                logger.info("Rollback completed successfully")
            except Exception as e:
                logger.error(f"Rollback failed: {e}")
                logger.critical(
                    f"Mirrorlist may be broken! "
                    f"Manually restore from: {self.backup_path}"
                )
        else:
            logger.warning("No backup available for rollback")
