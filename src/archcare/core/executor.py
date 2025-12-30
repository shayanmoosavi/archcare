"""
Task executor for archcare.

Handles task instantiation and execution coordination.
"""

from datetime import datetime, timedelta
from loguru import logger

from archcare.config import AppSettings, AppState, ConfigLoader, TaskConfig, TaskType
from archcare.core.models import TaskResult
from archcare.tasks.base import BaseTask


class TaskExecutor:
    """
    Coordinates task execution and state management.

    This class:
    - Instantiates tasks from their configuration
    - Manages task execution lifecycle
    - Updates task state after execution
    - Determines when tasks are due to run
    """

    def __init__(
        self,
        config_loader: ConfigLoader,
        settings: AppSettings,
        state: AppState,
        task_registry: dict[str, type[BaseTask]] | None = None,
    ):
        """
        Initialize task executor.

        Args:
            config_loader: ConfigLoader for loading configurations
            settings: Application settings
            state: Application state (for tracking runs)
            task_registry: Map of command name to task class
                          This will be populated as we implement tasks
        """
        self.config_loader = config_loader
        self.settings = settings
        self.state = state
        self.task_registry = task_registry or {}

    def register_task(self, command: str, task_class: type[BaseTask]) -> None:
        """
        Register a task class for a command.

        Args:
            command: Command identifier (e.g., "failed-services")
            task_class: Task class that handles this command

        Example:
            executor.register_task("failed-services", FailedServicesTask)
        """
        self.task_registry[command] = task_class
        logger.debug(f"Registered task: {command} -> {task_class.__name__}")

    def create_task(self, task_config: TaskConfig) -> BaseTask:
        """
        Create a task instance from its configuration.

        Args:
            task_config: Task configuration

        Returns:
            Instantiated task object

        Raises:
            ValueError: If task command is not registered
        """
        task_class = self.task_registry.get(task_config.command)

        if not task_class:
            raise ValueError(
                f"No task registered for command: {task_config.command}. "
                f"Available commands: {list(self.task_registry.keys())}"
            )

        return task_class(config=task_config, settings=self.settings)

    def execute_task(self, task_name: str) -> TaskResult:
        """
        Execute a single task by name.

        Args:
            task_name: Name of the task to execute

        Returns:
            TaskResult from task execution

        Raises:
            ValueError: If task not found or not enabled
        """
        # Load task configuration
        tasks_config = self.config_loader.load_tasks()
        task_config = tasks_config.get_task(task_name)

        if not task_config:
            raise ValueError(f"Task not found: {task_name}")

        if not task_config.enabled:
            raise ValueError(f"Task is disabled: {task_name}")

        # Create and run task
        task = self.create_task(task_config)
        result = task.run()

        # Update state
        self._update_state(task_config, result)

        return result

    def execute_all(self, task_type: TaskType | None = None) -> dict[str, TaskResult]:
        """
        Execute all enabled tasks, optionally filtered by type.

        Args:
            task_type: Filter by "automated" or "manual" (None = all)

        Returns:
            Dictionary mapping task names to their results

        Reason for returning dict instead of list:
        - Easy lookup of specific task results
        - Preserves task names with results
        - Better for error reporting and logging
        """
        tasks_config = self.config_loader.load_tasks()

        # Get tasks to execute
        if task_type:
            tasks_to_run = tasks_config.get_tasks_by_type(task_type)
        else:
            tasks_to_run = tasks_config.get_enabled_tasks()

        logger.info(f"Executing {len(tasks_to_run)} tasks")

        results = {}
        for task_name, task_config in tasks_to_run.items():
            try:
                logger.info(f"Running task: {task_name}")
                result = self.execute_task(task_name)
                results[task_name] = result
            except Exception as e:
                logger.error(f"Failed to execute task {task_name}: {e}")
                # Continue with other tasks even if one fails
                # (unless it's an unrecoverable error)

        return results

    def get_due_tasks(self) -> dict[str, TaskConfig]:
        """
        Get all tasks that are currently due to run.

        Returns:
            Dictionary of task names to their configurations
        """
        from archcare.core.scheduler import TaskScheduler

        tasks_config = self.config_loader.load_tasks()
        scheduler = TaskScheduler(tasks_config, self.state)

        # Get schedule info from scheduler
        due_schedule_info = scheduler.get_due_tasks()

        # Convert to dict of TaskConfig for execution purposes
        due_tasks = {}
        for info in due_schedule_info:
            task_config = tasks_config.get_task(info.task_name)
            if task_config:
                due_tasks[info.task_name] = task_config

        return due_tasks

    def _update_state(self, task_config: TaskConfig, result: TaskResult):
        """
        Update task state after execution.

        Args:
            task_config: Configuration of executed task
            result: Result from task execution

        Reason for private method:
        - Keeps state management logic centralized
        - Automatically calculates next due date
        - Ensures state is always updated after execution
        """
        # Calculate next due date
        next_due = datetime.now() + timedelta(days=task_config.frequency)

        # Update state
        self.state.update_task_state(
            task_name=task_config.name,
            status=result.status,
            next_due=next_due,
            error=str(result.error) if result.error else None,
        )

        # Save state to disk
        self.config_loader.save_state(self.state)

        logger.debug(f"Updated state for {task_config.name}: next due {next_due}")
