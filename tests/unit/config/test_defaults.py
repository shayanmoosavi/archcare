"""Unit tests for the programmatically-built default TOML documents."""

import tomlkit

from archcare.config.defaults import (
    build_ignored_services_toml,
    build_settings_toml,
    build_tasks_toml,
)
from archcare.config.models import (
    AppSettings,
    IgnoredServicesConfig,
    TaskConfig,
    TasksConfig,
    TaskType,
)


class TestBuildSettingsToml:
    def test_values_match_appsettings_defaults(self):
        """The whole point: this can never drift from AppSettings' own
        defaults, because it's built FROM them, not re-typed."""
        doc = build_settings_toml()
        defaults = AppSettings()

        assert doc["log_level"] == defaults.log_level.value
        assert doc["dry_run"] == defaults.dry_run
        assert doc["mirrorlist"]["country"] == defaults.mirrorlist.country
        assert (
            doc["maintenance_check"]["critical_threshold_days"]
            == defaults.maintenance_check.critical_threshold_days
        )

    def test_produces_valid_toml_that_round_trips(self):
        doc = build_settings_toml()
        reparsed = tomlkit.parse(tomlkit.dumps(doc))
        assert reparsed["log_level"] == "INFO"

    def test_trailing_comments_present(self):
        content = tomlkit.dumps(build_settings_toml())
        assert '# "terminal", "file", "both"' in content
        assert "# For critical issues" in content


class TestBuildTasksToml:
    def test_all_tasks_present(self):
        doc = build_tasks_toml()
        task_sections = [k for k, v in doc.items() if isinstance(v, dict)]
        assert len(task_sections) == 11

    def test_produces_valid_task_configs(self):
        doc = build_tasks_toml()
        reparsed = tomlkit.parse(tomlkit.dumps(doc))

        tasks = {
            name: TaskConfig(**{**data, "name": name})
            for name, data in reparsed.items()
            if isinstance(data, dict)
        }
        config = TasksConfig(tasks=tasks)

        assert len(config.tasks) == 11
        assert config.tasks["maintenance-check"].task_type == TaskType.AUTOMATED
        assert config.tasks["health-check"].task_type == TaskType.MANUAL

    def test_uses_type_alias_not_field_name(self):
        content = tomlkit.dumps(build_tasks_toml())
        assert "task_type" not in content

    def test_does_not_write_name_as_a_key(self):
        content = tomlkit.dumps(build_tasks_toml())
        assert "name = " not in content


class TestBuildIgnoredServicesToml:
    def test_produces_valid_config(self):
        content = tomlkit.dumps(build_ignored_services_toml())
        config = IgnoredServicesConfig(**tomlkit.parse(content))
        assert "systemd-networkd-wait-online.service" in config.services
