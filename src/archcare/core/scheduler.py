"""
Task scheduling manager for the Archcare core layer.

This module provides [TaskScheduler][], which evaluates task configurations ([TasksConfig][])
and current execution history ([AppState][]) to calculate schedule states, overdue time periods,
and next-due schedules for recurrences. It maps scheduling evaluations to
[TaskScheduleInfo][] structures.

Scheduling decisions are evaluated dynamically by contrasting execution logs with task frequency
settings. This decouples individual automated scripts from managing recurrence state or
triggering timers, delegating scheduling status reporting to a single source of truth.

Key Concepts:
    - **Frequency-Based Recurrence**: Overdue status is measured by contrasting `next_due`
        (or last run timestamp offset by configuration recurrence frequency) with the current clock.
    - **Overdue Severity**: Tasks can be queried to filter only currently outstanding/due
        operations, sorted dynamically by those most overdue.

See Also:
    - [TaskConfig][archcare.config.models.TaskConfig]: Configuration defining execution intervals.
    - [AppState][]: State model tracking execution timestamps.
"""

from datetime import datetime, timedelta
from typing import NamedTuple

from archcare.config import AppState, TasksConfig


class TaskScheduleInfo(NamedTuple):
    """
    Detailed information about a task's schedule and overdue status.

    Attributes:
        task_name (str): Simple identifier of the task.
        is_due (bool): `True` if the task recurrence interval has expired or the task
            has never executed; `False` otherwise.
        last_run (datetime | None): Timestamp of the most recent execution, or `None` if
            the task has never executed.
        next_due (datetime | None): Calculated or recorded timestamp for the next scheduled
            run, or `None` if the task has never executed.
        days_overdue (int): Number of whole days the task is overdue. Defaults to `0` if
            the task is not overdue or has never executed.
        reason (str): Human-readable summary of the task's schedule status.
            (e.g., `"Never run before"`, `"Overdue by 3 day(s)"`, `"Due tomorrow"`,
            `"Due in 5 days"`).
    """

    task_name: str
    is_due: bool
    last_run: datetime | None
    next_due: datetime | None
    days_overdue: int
    reason: str


class TaskScheduler:
    """
    Manages task scheduling logic.

    Maintains orchestrating queries over the collection of all tasks to assess their
    due status, remaining intervals, and priority queues, facilitating dashboard queries,
    system state reports, and execution filtering.

    Attributes:
        tasks_config (TasksConfig): Source task definitions containing name, frequency,
            and enable statuses.
        state (AppState): Live application execution history containing timestamps of previous runs.

    Examples:
        >>> from datetime import datetime, timedelta
        >>> from archcare.config import (
        ...     TasksConfig,
        ...     TaskConfig,
        ...     AppState,
        ...     TaskState,
        ...     TaskType,
        ...     TaskStatus,
        ... )
        >>> from archcare.core.scheduler import TaskScheduler
        >>>
        >>> # Setup dummy task configurations
        >>> tasks_config = TasksConfig(
        ...     tasks={
        ...         "health-check": TaskConfig(
        ...             name="health-check",
        ...             type=TaskType.AUTOMATED,
        ...             frequency=7,
        ...             description="Core system health",
        ...             enabled=True,
        ...         )
        ...     }
        ... )
        >>>
        >>> # Setup fresh empty state
        >>> state = AppState(tasks={})
        >>> scheduler = TaskScheduler(tasks_config, state)
        >>>
        >>> # Retrieve schedule for task never executed
        >>> info = scheduler.get_schedule_info("health-check")
        >>> info.is_due
        True
        >>> info.reason
        'Never run before'
        >>>
        >>> # Simulate a task run that occurred 2 days ago (not due yet)
        >>> now = datetime.now()
        >>> last_run = now - timedelta(days=2)
        >>> next_due = last_run + timedelta(days=7)
        >>> state.tasks["health-check"] = TaskState(
        ...     last_run=last_run, next_due=next_due, last_status=TaskStatus.SUCCESS, run_count=1
        ... )
        >>> info = scheduler.get_schedule_info("health-check")
        >>> info.is_due
        False
        >>> info.days_overdue
        0

    See Also:
        - [TaskScheduleInfo][]: Named tuple detailing a single task's schedule.
    """

    def __init__(self, tasks_config: TasksConfig, state: AppState):
        """
        Initialize the task scheduler.

        Args:
            tasks_config (TasksConfig): Complete task configurations dictionary.
            state (AppState): Application state tracking execution history.
        """
        self.tasks_config = tasks_config
        self.state = state

    def get_schedule_info(self, task_name: str) -> TaskScheduleInfo:
        """
        Calculate detailed scheduling information for a specific task.

        Synthesizes configuration values and state details to determine whether the
        given task is currently due, calculates its exact next due timestamp, evaluates
        the overdue day count, and constructs a descriptive status reason string.

        Args:
            task_name (str): Simple string identifier of the task.

        Returns:
            TaskScheduleInfo: Comprehensive scheduling status for the specified task.

        Raises:
            UnknownTaskError: If the specified `task_name` is not defined in `tasks_config`.
                (propagated from [TasksConfig.get_task][]).
        """
        task_config = self.tasks_config.get_task(task_name)

        task_state = self.state.get_task_state(task_name)

        # Task never run
        if not task_state.last_run:
            return TaskScheduleInfo(
                task_name=task_name,
                is_due=True,
                last_run=None,
                next_due=None,
                days_overdue=0,
                reason="Never run before",
            )

        # Calculate schedule info
        frequency_delta = timedelta(days=task_config.frequency)
        next_due = task_state.next_due or (task_state.last_run + frequency_delta)
        time_until_due = next_due - datetime.now()

        is_due = time_until_due.total_seconds() <= 0
        days_overdue = max(0, (-time_until_due).days)

        # Generate reason message
        if is_due:
            reason = "Due now" if days_overdue == 0 else f"Overdue by {days_overdue} day(s)"
        else:
            days_until = time_until_due.days + 1
            reason = "Due tomorrow" if days_until == 1 else f"Due in {days_until} days"

        return TaskScheduleInfo(
            task_name=task_name,
            is_due=is_due,
            last_run=task_state.last_run,
            next_due=next_due,
            days_overdue=days_overdue,
            reason=reason,
        )

    def get_due_tasks(self) -> list[TaskScheduleInfo]:
        """
        Collect all enabled tasks that are currently due or overdue.

        Filters the set of enabled tasks to identify those currently needing execution,
        sorting the results with the most overdue tasks positioned first.

        Returns:
            (list[TaskScheduleInfo]): A list of scheduling details for due tasks,
                sorted descending by `days_overdue`.
        """
        due_tasks = []

        for task_name in self.tasks_config.get_enabled_tasks().keys():
            info = self.get_schedule_info(task_name)
            if info.is_due:
                due_tasks.append(info)

        # Sort by days overdue (most overdue first)
        due_tasks.sort(key=lambda x: x.days_overdue, reverse=True)

        return due_tasks

    def get_all_schedule_info(self) -> list[TaskScheduleInfo]:
        """
        Collect schedule information for all enabled tasks.

        Generates and aggregates scheduling info records for every enabled task,
        sorting them to highlight priorities where attention is most urgently needed.

        Returns:
            (list[TaskScheduleInfo]): A list of scheduling details for all enabled tasks,
                sorted to place due tasks first, followed by remaining tasks sorted by
                increasing `next_due` timestamps.
        """
        all_info = []

        for task_name in self.tasks_config.get_enabled_tasks().keys():
            info = self.get_schedule_info(task_name)
            all_info.append(info)

        # Sort by: due tasks first, then by next_due date
        all_info.sort(
            key=lambda x: (
                not x.is_due,  # False (due) sorts before True (not due)
                x.next_due or datetime.max,  # None sorts last
            )
        )

        return all_info

    def get_maintenance_summary(self) -> dict[str, int]:
        """
        Compile an at-a-glance summary of system-wide maintenance status.

        Calculates aggregated metric counts covering active tasks, currently due
        actions, overdue tasks, and upcoming deadlines, facilitating dashboard summaries.

        Returns:
            (dict[str, int]): A summary dictionary containing the following keys:

                - `'total'`: Total count of active/enabled tasks.
                - `'due'`: Count of tasks currently due/overdue for execution.
                - `'overdue'`: Count of tasks specifically overdue by 1 or more days.
                - `'upcoming'`: Count of tasks currently not due but scheduling recurrence
                  falls within the next 7 days.
        """
        all_info = self.get_all_schedule_info()

        due_count = sum(1 for info in all_info if info.is_due)
        overdue_count = sum(1 for info in all_info if info.days_overdue > 0)

        # Count upcoming (due within 7 days but not yet due)
        upcoming_count = 0
        for info in all_info:
            if not info.is_due and info.next_due is not None:
                days_until = (info.next_due - datetime.now()).days
                if days_until <= 7:
                    upcoming_count += 1

        return {
            "total": len(all_info),
            "due": due_count,
            "overdue": overdue_count,
            "upcoming": upcoming_count,
        }
