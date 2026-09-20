# Class Relationships

This page is the structural complement to the [Architecture Overview](index.md),
[Task Execution Lifecycle](task-lifecycle.md),
[Registry, ports & extensibility](registry-and-ports.md), and
[Configuration & state](configuration.md) pages. Where those pages explain flow, config, and wiring,
this page shows the static class relationships: inheritance, composition, delegation, and
port implementation.

Diagrams use [Mermaid](https://mermaid.js.org/) and match source-code names so every arrow can be
traced back to a real class or module.

## Diagram conventions

- **Solid arrow with hollow triangle** = inheritance / protocol implementation.
- **Solid arrow with hollow diamond** = aggregation (has-a).
- **Solid arrow with filled diamond** = composition / ownership.
- **Dashed arrow** = dependency / delegates-to.
- **Solid line** = association (two-way dependency).
- Participant names match the source exactly (`TaskExecutor`, `BaseTask`, `CliInteraction`,
  `AppState`, etc.).

## Task execution classes

```mermaid
classDiagram
    class BaseTask {
        <<abstract>>
        +config: TaskConfig
        +settings: AppSettings
        +notification_manager: NotificationManager | None
        +progress: TaskProgress
        +run() TaskResult
        +pre_check() tuple[bool, str]
        +should_run() tuple[bool, str, SkipReason | None]
        +execute()* TaskResult
        +post_execute(result)
        +rollback()
    }

    class FailedServicesTask
    class HealthCheckTask
    class MirrorlistUpdateTask
    class MaintenanceCheckTask

    BaseTask <|-- FailedServicesTask
    BaseTask <|-- HealthCheckTask
    BaseTask <|-- MirrorlistUpdateTask
    BaseTask <|-- MaintenanceCheckTask
```

Each concrete task is a thin subclass. The lifecycle contract lives in
[`BaseTask`][archcare.core.base_task.BaseTask]; tasks only override the hooks they need.

## Executor and registry

```mermaid
classDiagram
    class TaskExecutor {
        +config_loader: ConfigLoader
        +settings: AppSettings
        +state: AppState
        +task_registry: TaskRegistry
        +user_context: UserContext
        +interaction: TaskInteraction
        +progress: TaskProgress
        +execute_task(name, force) TaskResult
        -_create_task(config) BaseTask
        -_update_state(config, result)
    }

    class TaskRegistry {
        +get_task_class(name)
        +get_formatter_class(name)
        +names()
    }

    class TaskDescriptor {
        +name: str
        +task_class: type[BaseTask]
        +formatter_class: type[TaskDetailFormatter]
    }

    class BaseTask {
        <<abstract>>
        +run() TaskResult
        +execute()* TaskResult
    }

    class TaskResult~TDetails~ {
        +status: TaskStatus
        +message: str
        +details: TDetails | None
        +duration_seconds: float | None
        +error: str | None
    }

    TaskExecutor o-- TaskRegistry : resolves names
    TaskRegistry *-- TaskDescriptor : built from
    TaskExecutor ..> BaseTask : creates via registry
    TaskExecutor ..> TaskResult : returns
```

[`TaskExecutor`][archcare.core.executor.TaskExecutor] is the orchestrator. It never imports task
classes directly; it asks [`TaskRegistry`][archcare.core.task_registry.TaskRegistry] for them by
name. The registry is a mapping of task names to
[`TaskDescriptor`][archcare.core.task_registry.TaskDescriptor], which is assembled once in
[`AppContext`][archcare.cli.context.AppContext] and then passed to the executor. The executor
creates task instances by calling the `task_class` attribute of the descriptor. Formatters are
resolved separately at render time by
[`TaskPresenter`][archcare.cli.presenters.task_presenter.TaskPresenter] from the same registry. See
[task lifecycle](task-lifecycle.md) for details.

## Port protocols and CLI adapters

```mermaid
classDiagram
    class TaskInteraction {
        <<Protocol>>
        +notify(message, level)
        +confirm(prompt) bool
    }

    class TaskProgress {
        <<Protocol>>
        +start(total)
        +advance(step)
        +stop()
        +pause()
        +spinner(label)
    }

    class TaskDetailFormatter {
        <<Protocol>>
        +format(details) list[str]
    }

    class CliInteraction {
        +notify(message, level)
        +confirm(prompt) bool
    }

    class NonInteractive {
        +notify(message, level)
        +confirm(prompt) bool
    }

    class RichProgress {
        +start(total)
        +advance(step)
        +stop()
        +pause()
        +spinner(label)
    }

    class NoOpProgress {
        +start(total)
        +advance(step)
        +stop()
        +pause()
        +spinner(label)
    }

    TaskInteraction <|.. CliInteraction
    TaskInteraction <|.. NonInteractive
    TaskProgress <|.. RichProgress
    TaskProgress <|.. NoOpProgress

    class DefaultFormatter {
        +format(details) list[str]
    }

    TaskDetailFormatter <|.. DefaultFormatter
    note for DefaultFormatter "Other concrete formatters also exist"
```

`core/` defines the ports; `cli/` provides the implementations. A future GUI would implement the
same three protocols without changing `core/` or `config/`.

## Config and state models

```mermaid
classDiagram
    class ConfigLoader {
        +load_settings() AppSettings
        +save_settings(settings)
        +load_tasks() TasksConfig
        +save_tasks(tasks)
        +load_ignored_services() IgnoredServicesConfig
        +save_ignored_services(ignored_services)
    }

    class AppSettings {
        +log_level: LogLevel
        +log_retention_days: int
        +dry_run: bool
        +user: str | None
        +home_dir: Path
        +config_dir: Path
        +state_file: Path
        +log_dir: Path
        +mirrorlist: MirrorlistSettings
        +maintenance_check: MaintenanceCheckSettings
        +ensure_directories()
    }

    class AppState {
        +tasks: dict[str, TaskState]
        +last_updated: datetime
        +get_task_state(name)
        +update_task_state(name, **kwargs)
    }

    class TaskState {
        +last_run: datetime | None
        +last_status: TaskStatus | None
        +next_due: datetime | None
        +run_count: int
        +last_error: str | None
        +skip_reason: SkipReason | None
    }

    class TasksConfig {
        +get_task(name)
        +get_enabled_tasks()
    }

    class TaskConfig {
        +name: str
        +type: TaskType
        +frequency: int
        +description: str
        +enabled: bool
    }

    class IgnoredServicesConfig {
        +services: list[str]
        +is_ignored(name) bool
    }

    ConfigLoader -- AppSettings
    ConfigLoader -- TasksConfig
    ConfigLoader -- IgnoredServicesConfig
    ConfigLoader -- AppState
    AppSettings *-- MirrorlistSettings
    AppSettings *-- MaintenanceCheckSettings
    AppState o-- TaskState : many
    TasksConfig o-- TaskConfig : many
```

[`ConfigLoader`][archcare.config.loader.ConfigLoader] is the single gateway to persistence, but the
model relationships above are what it reads and writes.
[`AppSettings`][archcare.config.models.AppSettings] owns all computed paths;
[`AppState`][archcare.config.models.AppState] owns per-task history.

## ConfigLoader persistence contract

```mermaid
flowchart TD
    LO[ConfigLoader] -->|load_tasks / save_tasks| TASKS["tasks.toml"]
    LO -->|load_settings / save_settings| SETTINGS["settings.toml"]
    LO -->|load_ignored_services / save_ignored_services| IGNORED["ignored-services.toml"]
    LO -->|load_state / save_state| STATE["state.json"]

    TASKS --> TC["TasksConfig"]
    SETTINGS --> AS["AppSettings"]
    IGNORED --> ISC["IgnoredServicesConfig"]
    STATE --> ASTATE["AppState"]
```

`ConfigLoader` is the single gateway to persistence. It maps each file to its
[Pydantic](https://pydantic.dev/) model type: `tasks.toml` ↔ `TasksConfig`,
`settings.toml` ↔ `AppSettings`, `ignored-services.toml` ↔
[`IgnoredServicesConfig`][archcare.config.models.IgnoredServicesConfig],
and `state.json` ↔ `AppState`.

## Services wiring

```mermaid
flowchart TD
    CLI[CLI command] --> CTX[AppContext]
    CTX --> EX[TaskExecutor]
    CTX --> SVC[TaskService]
    SVC --> EX
    SVC --> RESP[TaskRunResponse]
    CTX --> PRES[TaskPresenter]
    PRES --> RESP
    EX --> REG[TaskRegistry]
    EX --> LO[ConfigLoader]
    EX --> T[BaseTask subclass]
    T --> RES["TaskResult[TDetails]"]
    RES --> EX
    EX --> ST[AppState]
    LO --> ST
```

This is the wiring view: [`AppContext`][archcare.cli.context.AppContext] builds shared objects once,
commands construct one service, and the service delegates to the executor. Results flow back through
response DTOs to presenters.

## Presenter and formatter rendering

```mermaid
flowchart TD
    RESP[TaskRunResponse] --> PRES[TaskPresenter]
    PRES --> SHELL[Universal panel shell<br/>status, message, duration, error]
    PRES -->|verbose + details exists| REG[TaskRegistry]
    REG -->|"get_formatter_class(name)"| FMT[TaskDetailFormatter subclass]
    FMT -->|"format(details)"| LINES[Rich detail lines]
    SHELL --> OUT[Rendered terminal output]
    LINES --> OUT
```

The presenter owns terminal rendering. It builds the universal shell itself, then delegates
domain-specific detail rendering to the task's registered formatter. This keeps task code free of
presentation concerns and preserves the core/config boundary.

## Related pages

- [Task Execution Lifecycle](task-lifecycle.md) — the runtime sequence that these classes
  participate in
- [Registry, ports & extensibility](registry-and-ports.md) — how task names resolve through
  the registry
- [Configuration & state](configuration.md) — the full config/state schema
