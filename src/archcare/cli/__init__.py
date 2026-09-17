"""
CLI layer for Archcare.

The outermost layer: Typer commands, presenters, and terminal rendering. Built on top of the
`services/` layer, which it reaches only through [`AppContext`][archcare.cli.context.AppContext]
— the per-invocation context wired by the root callback. This is also where the port protocols
defined in `core/` (`TaskInteraction`, `TaskProgress`, `TaskDetailFormatter`) get their CLI-side
implementations (`CliInteraction`, `RichProgress`, the presenter formatters), keeping `core/` and
`services/` free of any CLI dependency.

Exports only the console-script entry point [`main`][archcare.cli.app.main].

Modules:
    commands: The defined Typer sub-apps for the CLI layer
    presenters: The presenter layer for the CLI
    app: The assembled Typer CLI interface
    context: The shared application context for the Typer commands
    interaction: The CLI adaptor of the
        [`TaskInteraction`][archcare.core.interaction.TaskInteraction] port
    progress: The CLI adaptor of the
        [`TaskProgress`][archcare.core.progress.TaskProgress] port

See Also:
    - [`archcare.cli.app`][]: Root Typer application assembly
    - [`archcare.cli.context`][]: Per-invocation context and task registry
"""

from .app import main

__all__ = ["main"]
