"""One-time setup Typer commands for Archcare."""

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


@setup_app.command("config")
def setup_config():
    """
    Initialize archcare configuration files.

    This creates default configuration files if they don't exist.
    """
    service = ConfigService()

    SetupPresenter.config_header(service.config_dir)

    existing = service.check_existing()
    if existing:
        SetupPresenter.existing_files_warning(existing)
        if not typer.confirm("Overwrite existing files?"):
            SetupPresenter.init_cancelled()
            raise typer.Exit(0)

    result = service.initialize()
    SetupPresenter.render_config_init(result)


@setup_app.command("timers")
def setup_timers(
    ctx: typer.Context,
    enable: bool = typer.Option(
        True, "--enable/--no-enable", help="Enable timers after installation"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be done without doing it"
    ),
):
    """
    Set up systemd timers for automated task execution.

    This command:
    - Creates systemd service and timer templates
    - Installs them to /etc/systemd/system/
    - Optionally enables specified timers

    Example:
        archcare setup timers --dry-run
        archcare setup timers
    """
    try:
        user, home_dir = resolve_systemd_target_user()
    except NotRootError:
        SetupPresenter.not_root()
        raise typer.Exit(1)
    except UserDetectionError as e:
        SetupPresenter.error(str(e))
        raise typer.Exit(1)

    try:
        # Built for the SUDO_USER target, not ctx.obj's own user (which is
        # derived from ARCHCARE_USER and unset in this sudo-driven flow).
        executor = ctx.obj.executor_for_user(user)
        service = TimerService(executor, user, home_dir)

        install_response = service.install_templates(dry_run)
        SetupPresenter.render_template_installation(install_response, dry_run)

        print()
        reload_response = service.reload(dry_run)
        SetupPresenter.render_systemd_reload(reload_response, dry_run)

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
        raise typer.Exit(1)
    except Exception as e:
        SetupPresenter.error(f"Setup failed: {e}")
        logger.exception("Setup error")
        raise typer.Exit(1)
