"""
Base task implementation for archcare.

All maintenance tasks inherit from BaseTask.
"""

import time
from abc import ABC, abstractmethod

from loguru import logger

from archcare.config import AppSettings, TaskConfig, SkipReason
from archcare.core.models import TaskResult, TaskStep, failed, skipped
from archcare.utils import setup_task_logging


class BaseTask(ABC):
    """
    Abstract base class for all maintenance tasks.

    All tasks must implement:
    - execute(): Main task logic

    Tasks can optionally override:
    - pre_check(): Verify prerequisites before running
    - post_execute(): Cleanup after execution
    - rollback(): Undo changes if execution fails
    - should_run(): Additional logic to determine if task should run
    """

    def __init__(self, config: TaskConfig, settings: AppSettings):
        """
        Initialize base task.

        Args:
            config: Task-specific configuration
            settings: Application settings
        """
        self.config = config
        self.settings = settings
        self.name = config.name
        self._start_time: float = 0.0

    def set_start_time(self, start_time: float = time.time()):
        self._start_time = start_time

    @abstractmethod
    def execute(self) -> TaskResult:
        """
        Execute the main task logic.

        This method must be implemented by all task subclasses.
        It should contain the core functionality of the task.

        Returns:
            TaskResult indicating success/failure and details

        Raises:
            Exception: Any unhandled exceptions will be caught by run()
        """
        pass

    def pre_check(self) -> tuple[bool, str]:
        """
        Verify prerequisites before task execution.

        Override this to check for required tools, permissions, or conditions.

        Returns:
            Tuple of (can_run: bool, reason: str)
            If can_run is False, the task will be skipped with the given reason.

        Example:
            def pre_check(self) -> tuple[bool, str]:
                if not shutil.which("systemctl"):
                    return False, "systemctl command not found"
                return True, ""
        """
        return True, ""

    def should_run(self) -> tuple[bool, str, SkipReason | None]:
        """
        Additional logic to determine if task should run.

        This is separate from pre_check() and is meant for runtime decisions
        beyond just checking prerequisites. For example, checking if there's
        actually work to do.

        Returns:
            Tuple of (should_run: bool, reason: str, skip_reason: SkipReason)
            If should_run is False, task is skipped with the given reason.

        Example:
            def should_run(self) -> tuple[bool, str]:
                if no_failed_services():
                    return False, "No failed services found", SkipReason.NO_WORK_NEEDED
                return True, ""
        """
        return True, "", None

    def post_execute(self, result: TaskResult) -> None:
        """
        Cleanup or follow-up actions after task execution.

        This runs after execute() regardless of success/failure.
        Override to perform cleanup, send notifications, etc.

        Args:
            result: The result from execute()

        Example:
            def post_execute(self, result: TaskResult) -> None:
                if result.is_failed():
                    self.send_notification(f"Task {self.name} failed")
        """
        pass

    def rollback(self) -> None:
        """
        Attempt to rollback changes if task execution fails.

        Override this for tasks that make changes that can be undone.
        This is called automatically if execute() raises an exception.

        Example:
            def rollback(self) -> None:
                if self.backup_file.exists():
                    shutil.copy(self.backup_file, self.original_file)
        """
        pass

    def report_progress(self, step: TaskStep) -> None:
        """
        Report progress during task execution.

        Use this to provide real-time feedback during long-running tasks.

        Args:
            step: TaskStep describing the current operation

        Example:
            self.report_progress(TaskStep(
                name="Updating mirrors",
                status=TaskStatus.SUCCESS,
                message="Fetched 10 mirrors"
            ))
        """
        logger.info(f"[{self.name}] {step}")

    def run(self) -> TaskResult:
        """
        Run the complete task workflow with error handling.

        This method orchestrates the entire task execution:
        1. Pre-checks (prerequisites)
        2. Should-run checks (runtime decisions)
        3. Task execution
        4. Post-execution cleanup
        5. Rollback on failure

        Returns:
            TaskResult with execution details and timing
        """
        self.set_start_time()

        logger.info(f"Starting task: {self.name}")
        logger.debug(f"Task config: {self.config}")

        handler_id = setup_task_logging(self.name, self.settings)
        try:
            with logger.contextualize(task=self.name):
                # Check prerequisites
                can_run, reason = self.pre_check()
                if not can_run:
                    logger.warning(f"Pre-check failed for {self.name}: {reason}")
                    return self.create_result(
                        skipped(
                            f"Pre-check failed: {reason}",
                            skip_reason=SkipReason.DEPENDENCY_FAILED,
                        )
                    )

                # Check if task should run
                should_run, reason, skip_reason = self.should_run()
                if not should_run:
                    logger.info(f"Task {self.name} skipped: {reason}")
                    return self.create_result(skipped(reason, skip_reason))

                # Execute main task logic
                logger.info(f"Executing {self.name}")
                result = self.execute()

                # Post-execution cleanup
                self.post_execute(result)

                # Log result
                if result.is_success():
                    logger.success(f"Task {self.name} completed successfully")
                elif result.is_failed():
                    logger.error(f"Task {self.name} failed: {result.message}")
                else:
                    logger.info(f"Task {self.name} finished: {result.status}")

                return self.create_result(result)

        except Exception as e:
            logger.exception(f"Unhandled exception in task {self.name}")

            # Attempt rollback
            try:
                logger.info(f"Attempting rollback for {self.name}")
                self.rollback()
                logger.info(f"Rollback completed for {self.name}")
            except Exception as rollback_error:
                logger.error(f"Rollback failed for {self.name}: {rollback_error}")

            return self.create_result(
                failed(message=f"Task execution failed: {str(e)}", error=e)
            )
        finally:
            # Remove task-specific log handler
            logger.remove(handler_id)

    def create_result(self, result: TaskResult) -> TaskResult:
        """
        Add timing information to result.

        Args:
            result: TaskResult from execute()

        Returns:
            TaskResult with duration added

        Reason:
        - Ensures all results have accurate timing
        - Keeps execute() methods clean of timing logic
        """
        result.duration_seconds = time.time() - self._start_time
        return result

    def __str__(self) -> str:
        """String representation of task."""
        return f"{self.__class__.__name__}(name={self.name})"

    def __repr__(self) -> str:
        """Detailed string representation."""
        return (
            f"{self.__class__.__name__}("
            f"name={self.name}, "
            f"type={self.config.task_type}, "
            f"frequency={self.config.frequency})"
        )
