"""
Task scheduling for archcare.

Determines which tasks should run and when.
"""

from datetime import datetime, timedelta
from typing import NamedTuple

from archcare.config import AppState, TasksConfig, TaskType


class TaskScheduleInfo(NamedTuple):
    """
    Information about a task's schedule status.
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

    This class handles:
    - Determining if tasks are due
    - Calculating overdue periods
    - Providing schedule information for display
    """

    def __init__(self, tasks_config: TasksConfig, state: AppState):
        """
        Initialize scheduler.

        Args:
            tasks_config: Task configurations
            state: Application state with run history
        """
        self.tasks_config = tasks_config
        self.state = state

    def get_schedule_info(self, task_name: str) -> TaskScheduleInfo:
        """
        Get detailed schedule information for a task.

        Args:
            task_name: Name of the task

        Returns:
            TaskScheduleInfo with schedule details

        Raises:
            ValueError: If task doesn't exist
        """
        task_config = self.tasks_config.get_task(task_name)
        if not task_config:
            raise ValueError(f"Task not found: {task_name}")

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
        next_due = task_state.next_due if task_state.next_due else task_state.last_run + frequency_delta
        time_until_due = next_due - datetime.now()

        is_due = time_until_due.total_seconds() <= 0
        days_overdue = max(0, -time_until_due.days)

        # Generate reason message
        if is_due:
            if days_overdue == 0:
                reason = "Due now"
            elif days_overdue == 1:
                reason = "Overdue by 1 day"
            else:
                reason = f"Overdue by {days_overdue} days"
        else:
            days_until = time_until_due.days + 1
            if days_until == 1:
                reason = "Due tomorrow"
            else:
                reason = f"Due in {days_until} days"

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
        Get all tasks that are currently due.

        Returns:
            List of TaskScheduleInfo for due tasks, sorted by days overdue
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
        Get schedule information for all enabled tasks.

        Returns:
            List of TaskScheduleInfo for all tasks, sorted by next due date

        Reason for sorting:
        - Shows tasks in order of when attention is needed
        - Due tasks appear at top
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

    def get_tasks_by_type(self, task_type: TaskType) -> list[TaskScheduleInfo]:
        """
        Get schedule info for tasks of a specific type.

        Args:
            task_type: "automated" or "manual"

        Returns:
            List of TaskScheduleInfo for matching tasks
        """
        type_tasks = self.tasks_config.get_tasks_by_type(task_type.value)

        schedule_info = []
        for task_name in type_tasks.keys():
            info = self.get_schedule_info(task_name)
            schedule_info.append(info)

        # Sort by due status and overdue amount
        schedule_info.sort(key=lambda x: (not x.is_due, -x.days_overdue))

        return schedule_info

    def should_notify(self, task_name: str, warning_days: int = 3) -> bool:
        """
        Check if user should be notified about a task.

        Args:
            task_name: Name of the task
            warning_days: Days before due to start warning (default: 3)

        Returns:
            True if notification should be sent
        """
        info = self.get_schedule_info(task_name)

        # Notify if overdue
        if info.is_due:
            return True

        # Notify if due soon
        if info.next_due:
            days_until = (info.next_due - datetime.now()).days
            return days_until <= warning_days

        return False

    def get_maintenance_summary(self) -> dict[str, int]:
        """
        Get a summary of maintenance status.

        Returns:
            Dictionary with counts:
            - total: Total enabled tasks
            - due: Tasks currently due
            - overdue: Tasks overdue by 1+ days
            - upcoming: Tasks due within 7 days

        Reason:
        - Provides at-a-glance system maintenance status
        - Useful for dashboard displays
        - Helps prioritize maintenance work
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
