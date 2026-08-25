"""
Base task implementation for Archcare.

Defines the abstract interface and core orchestrator workflow for all system
maintenance tasks. All concrete task classes (e.g., `FailedServicesTask`,
`HealthCheckTask`) must inherit from `BaseTask` and implement its core abstract
methods.

Key features:
    - Standardized execution workflow via the `run()` method
    - Pre-execution precondition and work-needed runtime checks
    - Automatic, robust rollback hook invocation on execution exceptions
    - Task-specific thread-safe file logging setup and cleanup
    - Timing metrics capturing and desktop notifications dispatch support
    - Real-time task progress reporting hook integration

See Also:
    - [TaskExecutor][archcare.core.executor.TaskExecutor]: Coordinates the lifecycle
        and execution of tasks
    - [TaskResult][]: Schema representation of task run outcomes
    - [TaskProgress][]: Protocol used to report execution milestones
"""

import time
from abc import ABC, abstractmethod
from typing import Any

from loguru import logger

from archcare.config import AppSettings, SkipReason, TaskConfig, setup_task_logging

from .models import TaskResult, TaskStep, failed, skipped
from .notifications import NotificationManager
from .progress import NoOpProgress, TaskProgress


class BaseTask(ABC):
    """
    Abstract base class defining the contract and workflow for all maintenance tasks.

    All tasks in the system are subclassed from `BaseTask`. It uses the Template
    Method design pattern: the `run()` method defines the exact execution skeleton,
    while subclasses customize behavior by implementing `execute()`, and optionally
    overriding `pre_check()`, `should_run()`, `post_execute()`, and `rollback()`.

    Methods:
        set_start_time: Set the task start timestamp.
        execute: *(abstract)* Execute the primary task maintenance logic.
        pre_check: Verify that all hard prerequisites for task execution are satisfied.
        should_run: Determine if the task has actual maintenance work to perform.
        post_execute: Cleanup or follow-up actions after task execution.
        rollback: Attempt to rollback changes if task execution fails.
        report_progress: Dispatch a progress update during execution.
        run: Orchestrate the complete task execution pipeline with safety guards and timing.
        create_result: Inject execution duration statistics into the completed `TaskResult`.
    """

    def __init__(
        self,
        config: TaskConfig,
        settings: AppSettings,
        notification_manager: NotificationManager | None = None,
        progress: TaskProgress | None = None,
    ):
        """
        Initialize the base task context.

        Args:
            config (TaskConfig): Task-specific configuration (e.g., enabled, frequency).
            settings (AppSettings): Application-wide settings (e.g., log levels, paths).
            notification_manager (NotificationManager | None): Desktop notification manager.
                Optional so tasks can be instantiated cheaply in unit tests.
            progress (TaskProgress | None): Real-time progress reporter. If None,
                uses a `NoOpProgress` stub.

        Side Effects:
            Initializes internal `_start_time` tracking variable to 0.0.
        """
        self.config = config
        self.settings = settings
        self.notification_manager = notification_manager
        self.progress = progress or NoOpProgress()
        self.name = config.name
        self._start_time: int | float = 0.0

    def set_start_time(self, start_time: int | float | None = None):
        """
        Set the task start timestamp.

        Used to calculate duration metrics for the task result.

        Args:
            start_time (int | float | None): Exact start epoch timestamp.
                If None, uses current `time.time()`.

        Side Effects:
            Mutates `self._start_time`.
        """
        self._start_time = start_time or time.time()

    @abstractmethod
    def execute(self) -> TaskResult[Any]:
        """
        Execute the primary task maintenance logic.

        Must be implemented by all subclasses. This contains the core functionality
        representing the actual task work.

        Returns:
            (TaskResult[Any]): Result indicating success/failure status and details.

        Raises:
            Exception: Any exception raised in this method triggers `rollback()`
                and is captured as a task failure by `run()`.
        """
        pass

    def pre_check(self) -> tuple[bool, str]:
        """
        Verify that all hard prerequisites for task execution are satisfied.

        Override this to check for mandatory command-line utilities, sudo privileges,
        or hardware preconditions. If this returns False, execution skips immediately
        without checking if work is needed.

        Returns:
            (tuple[bool, str]): A tuple of:

                - `can_run` (`bool`): True if all prerequisites are satisfied, False otherwise.
                - `reason` (`str`): Explanatory message when prerequisites fail (empty on success).

        Examples:
            >>> class DummyTask(BaseTask):
            ...     def execute(self) -> TaskResult[Any]: pass
            ...     def pre_check(self) -> tuple[bool, str]:
            ...         import shutil
            ...         if not shutil.which("reflector"):
            ...             return False, "reflector command missing"
            ...         return True, ""
        """
        return True, ""

    def should_run(self) -> tuple[bool, str, SkipReason | None]:
        """
        Determine if the task has actual maintenance work to perform.

        This runs after `pre_check()` succeeds. Use it to decide if the task
        should run or skip based on dynamic runtime criteria (e.g., checking if
        any systemd services are actually failed, or if thresholds are exceeded).

        Returns:
            (tuple[bool, str, SkipReason | None]): A tuple of:

                - `should_run` (`bool`): True if work needs to be performed, False otherwise.
                - `reason` (`str`): Explanatory reason when skipping (empty if running).
                - `skip_reason` (`SkipReason | None`): Skip classification constant, or None.

        Examples:
            >>> class DummyTask(BaseTask):
            ...     def execute(self) -> TaskResult[Any]: pass
            ...     def should_run(self) -> tuple[bool, str, SkipReason | None]:
            ...         work_needed = False
            ...         if not work_needed:
            ...             return False, "No updates found", SkipReason.NO_WORK_NEEDED
            ...         return True, "", None
        """
        return True, "", None

    def post_execute(self, result: TaskResult[Any]) -> None:
        """
        Cleanup or follow-up actions after task execution.

        Runs at the end of successful or failed `execute()` steps, but before final logging
        and cleanup handlers teardown. Override this if you wish to do additional steps after
        task execution, such as sending an status notification, cleaning up old report files,
        etc.

        Args:
            result (TaskResult[Any]): The completed result object returned by `execute()`.

        Examples:
            >>> class DummyTask(BaseTask):
            ...     def execute(self) -> TaskResult[None]: pass
            ...     def post_execute(self, result: TaskResult[Any]) -> None:
            ...         if result.is_failed() and self.notification_manager:
            ...             self.notification_manager.notify(f"Task failed: {result.message}")
        """
        return

    def rollback(self) -> None:
        """
        Attempt to rollback changes if task execution fails.

        This is invoked automatically by `run()` when `execute()` raises an unhandled
        exception. Override this in stateful tasks to restore backups or clean up
        partially-written files.

        Raises:
            Exception: Any exception raised within `rollback` is logged as critical,
                but does not override the primary execution failure.

        Examples:
            >>> class DummyTask(BaseTask):
            ...     def execute(self) -> TaskResult[None]: pass
            ...     def rollback(self) -> None:
            ...         # Restore backup configuration
            ...         pass
        """
        return

    def report_progress(self, step: TaskStep) -> None:
        """
        Dispatch a progress update during execution.

        Updates the console or GUI interface and writes a log entry with the progress step details.

        Args:
            step (TaskStep): Detailed step descriptor representing the current milestone.

        Side Effects:
            - Logs the progress step message at INFO level.
            - Mutates progress display state via `self.progress.advance()`.
        """
        logger.info(f"[{self.name}] {step}")
        self.progress.advance(step)

    def run(self) -> TaskResult[Any]:
        """
        Orchestrate the complete task execution pipeline with safety guards and timing.

        This method executes the entire lifecycle sequence:

        1. Set start execution time.
        2. Configure task-specific rotating log handlers.
        3. Invoke `pre_check()` to verify environment prerequisites.
        4. Invoke `should_run()` to decide if any dynamic work is required.
        5. Invoke `execute()` inside a contextualized logging handler.
        6. Invoke `post_execute()` for task-specific cleanups/analytics.
        7. If an exception occurs, log it and invoke `rollback()`.
        8. Teardown progress tracking and close task log files.

        Returns:
            (TaskResult[Any]): Standardized task run result containing status,
                error messages, detailed task context, and total duration.

        Side Effects:
            - Configures and tears down a Loguru file logging handler.
            - Stops progress tracking visual elements.
            - Performs filesystem and/or ownership state mutations depending on subclasses.

        See Also:
            - [pre_check][]: Prerequisite verification hook
            - [should_run][]: Dynamic execution requirement hook
            - [execute][]: Core logic hook
            - [post_execute][]: Post-run hook
            - [rollback][]: Error recovery hook
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
                logger.critical(f"Rollback failed for {self.name}: {rollback_error}")

            return self.create_result(
                failed(message=f"Task execution failed: {str(e)}", error=str(e))
            )
        finally:
            # Remove task-specific log handler
            if handler_id is not None:
                logger.remove(handler_id)
            # Finalize progress reporting
            self.progress.stop()

    def create_result(self, result: TaskResult[Any]) -> TaskResult[Any]:
        """
        Inject execution duration statistics into the completed `TaskResult`.

        Args:
            result (TaskResult[Any]): Completed result schema instance to finalize.

        Returns:
            (TaskResult[Any]): The same result instance containing calculated `duration_seconds`.

        Side Effects:
            Mutates `result.duration_seconds`.
        """
        result.duration_seconds = time.time() - self._start_time
        return result

    def __str__(self) -> str:
        """
        Generate a human-readable string representation of the task.

        Returns:
            str: Representation including the class name and specific task identifier.
        """
        return f"{self.__class__.__name__}(name={self.name})"

    def __repr__(self) -> str:
        """
        Generate a detailed machine/debugging string representation of the task.

        Returns:
            str: Detailed representation including class name, name, type, and frequency.
        """
        return (
            f"{self.__class__.__name__}("
            f"name={self.name}, "
            f"type={self.config.task_type}, "
            f"frequency={self.config.frequency})"
        )
