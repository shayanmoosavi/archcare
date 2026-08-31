"""
One-time setup Typer commands for Archcare.

Defines the `archcare setup` sub-app and its two commands:

- `setup config`: writes default TOML config files
    (`settings.toml`, `tasks.toml`, `ignored-services.toml`)
    to `~/.config/archcare/`, prompting to overwrite when they already exist.
- `setup timers`: installs the systemd template units (`archcare@.service`, `archcare@.timer`) into
    `/etc/systemd/system/`, reloads the daemon, and optionally enables+starts one timer per
    automated task. Must run via `sudo` since it touches `/etc/systemd/system/`; the target user is
    resolved from `SUDO_USER`.

All terminal output is delegated to [SetupPresenter][]; commands stay thin and translate each
failure mode into a presenter call plus a non-zero exit.
"""

from typing import Annotated

import typer
from loguru import logger

from archcare.cli.presenters import SetupPresenter
from archcare.services import (
    ConfigService,
    TimerService,
    resolve_systemd_target_user,
)
from archcare.services.exceptions import (
    NotRootError,
    SystemdReloadError,
    UserDetectionError,
)

setup_app = typer.Typer(help="One-time setup commands for bootstrapping Archcare.")


@setup_app.command(
    "config",
    help="""
Initialize archcare configuration files.

This creates default configuration files if they don't exist.
""",
)
def setup_config():
    """
    Initialize archcare configuration files.

    Prompts the user (via Typer) to overwrite any pre-existing TOML config files in the standard
    config directory, then delegates to [ConfigService.initialize][] to write the defaults. The full
    result is rendered via [SetupPresenter][].
    """
    service = ConfigService()

    SetupPresenter.config_header(service.config_dir)

    force = False
    existing = service.check_existing()
    if existing:
        SetupPresenter.existing_files_warning(existing)
        force = typer.confirm("Overwrite existing files?")

    result = service.initialize(force=force)
    SetupPresenter.render_config_init(result)


@setup_app.command(
    "timers",
    help="""
Set up systemd timers for automated task execution.

This command:
    - Creates systemd service and timer templates
    - Installs them to /etc/systemd/system/
    - Optionally enables specified timers

Example:
    archcare setup timers --dry-run
    archcare setup timers
""",
)
def setup_timers(
    ctx: typer.Context,
    enable: Annotated[
        bool,
        typer.Option("--enable/--no-enable", help="Enable timers after installation"),
    ] = True,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show what would be done without doing it")
    ] = False,
):
    """
    Set up systemd timers for automated task execution.

    Resolves the target user via [resolve_systemd_target_user][] (raising a non-zero exit if not
    root or if `SUDO_USER` is unset/invalid), then builds a fresh executor scoped to that user via
    [executor_for_user][archcare.cli.context.AppContext.executor_for_user] and constructs a
    [TimerService][] for the install/reload/enable pipeline. Each step is rendered by the matching
    [SetupPresenter][] helper. The `dry_run` flag short-circuits all filesystem writes and systemctl
    invocations, ending with the dry-run completion notice.

    Args:
        ctx (typer.Context): Typer context whose `obj` is an
            [AppContext][archcare.cli.context.AppContext].
        enable (bool): When `True`, enable+start the per-task timers after installation. Defaults
            to `True`.
        dry_run (bool): When `True`, perform no filesystem or systemctl writes; just print what
            would be done. Defaults to `False`.
    """
    try:
        user, home_dir = resolve_systemd_target_user()
    except NotRootError as e:
        SetupPresenter.not_root()
        raise typer.Exit(1) from e
    except UserDetectionError as e:
        SetupPresenter.error(str(e))
        raise typer.Exit(1) from e

    try:
        # Built for the SUDO_USER target, not ctx.obj's own user (which is
        # derived from ARCHCARE_USER and unset in this sudo-driven flow).
        executor = ctx.obj.executor_for_user(user)
        service = TimerService(executor, user, home_dir)

        install_response = service.install_templates(dry_run)
        SetupPresenter.render_template_installation(install_response)

        print()
        reload_response = service.reload(dry_run)
        SetupPresenter.render_systemd_reload(reload_response)

        SetupPresenter.templates_installed()

        automated_tasks = service.get_automated_tasks()
        if automated_tasks:
            setup_response = service.setup_timers(automated_tasks, dry_run, enable)
            SetupPresenter.render_timer_setup(setup_response)
        else:
            SetupPresenter.no_automated_tasks()

        SetupPresenter.useful_commands()

        if dry_run:
            SetupPresenter.dry_run_notice()

    except SystemdReloadError as e:
        SetupPresenter.error(str(e))
        raise typer.Exit(1) from e
    except Exception as e:
        SetupPresenter.error(f"Setup failed: {e}")
        logger.exception("Setup error")
        raise typer.Exit(1) from e
