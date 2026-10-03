"""Registry wiring checks for the task name → class mappings.

Full registry behaviour (lookups, duplicate detection, executor integration) is covered by
`tests/unit/cli/test_context.py`; this file only guards the one thing a typo in a task name or
a forgotten descriptor would hide until runtime: that every registered name resolves to the
classes the CLI expects.
"""

import pytest

from archcare.cli.context import DEFAULT_TASK_REGISTRY
from archcare.cli.presenters import (
    FailedServicesFormatter,
    HealthCheckFormatter,
    MaintenanceCheckFormatter,
    MirrorlistUpdateFormatter,
    SystemUpdateFormatter,
)
from archcare.core import BaseTask
from archcare.core.formatter import TaskDetailFormatter
from archcare.tasks import (
    FailedServicesTask,
    HealthCheckTask,
    MaintenanceCheckTask,
    MirrorlistUpdateTask,
    SystemUpdateTask,
)


class TestSystemUpdateRegistration:
    @pytest.mark.parametrize(
        "name",
        [
            "failed-services",
            "health-check",
            "maintenance-check",
            "mirrorlist-update",
            "system-update",
        ],
    )
    def test_registry_contains_implemented_descriptors(self, name: str):
        assert name in DEFAULT_TASK_REGISTRY.names()

    @pytest.mark.parametrize(
        ("name", "task", "formatter"),
        [
            ("failed-services", FailedServicesTask, FailedServicesFormatter),
            ("health-check", HealthCheckTask, HealthCheckFormatter),
            ("maintenance-check", MaintenanceCheckTask, MaintenanceCheckFormatter),
            ("mirrorlist-update", MirrorlistUpdateTask, MirrorlistUpdateFormatter),
            ("system-update", SystemUpdateTask, SystemUpdateFormatter),
        ],
    )
    def test_names_resolve_to_their_task_implementation_and_formatter(
        self, name: str, task: BaseTask, formatter: TaskDetailFormatter
    ):
        assert DEFAULT_TASK_REGISTRY.get_task_class(name) is task
        assert DEFAULT_TASK_REGISTRY.get_formatter_class(name) is formatter
