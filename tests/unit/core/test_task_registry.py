"""Unit tests for TaskRegistry."""

from typing import Any

import pytest

from archcare.core.formatter import DefaultFormatter
from archcare.core.task_registry import TaskDescriptor, TaskRegistry
from archcare.tasks.base import BaseTask


class FakeTaskA(BaseTask):
    def execute(self):
        raise NotImplementedError


class FakeTaskB(BaseTask):
    def execute(self):
        raise NotImplementedError


class FakeFormatter:
    def format(self, details: dict[str, Any]) -> list[str]:
        return [f"fake: {details}"]


@pytest.fixture
def registry() -> TaskRegistry:
    return TaskRegistry(
        (
            TaskDescriptor("task-a", FakeTaskA, FakeFormatter),
            TaskDescriptor("task-b", FakeTaskB),  # uses DefaultFormatter
        )
    )


class TestGetTaskClass:
    def test_returns_registered_task_class(self, registry: TaskRegistry):
        assert registry.get_task_class("task-a") is FakeTaskA

    def test_raises_value_error_for_unregistered_name(self, registry: TaskRegistry):
        with pytest.raises(ValueError, match="task-c"):
            registry.get_task_class("task-c")

    def test_error_message_lists_available_tasks(self, registry: TaskRegistry):
        with pytest.raises(ValueError) as exc_info:
            registry.get_task_class("task-c")

        assert "task-a" in str(exc_info.value)
        assert "task-b" in str(exc_info.value)


class TestGetFormatterClass:
    def test_returns_registered_formatter(self, registry: TaskRegistry):
        assert registry.get_formatter_class("task-a") is FakeFormatter

    def test_defaults_to_default_formatter_when_not_specified(
        self, registry: TaskRegistry
    ):
        assert registry.get_formatter_class("task-b") is DefaultFormatter

    def test_defaults_to_default_formatter_for_unregistered_name(
        self, registry: TaskRegistry
    ):
        assert registry.get_formatter_class("task-c") is DefaultFormatter


class TestNames:
    def test_returns_all_registered_names(self, registry: TaskRegistry):
        assert set(registry.names()) == {"task-a", "task-b"}
