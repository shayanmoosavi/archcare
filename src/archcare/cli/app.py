"""Typer CLI interface for Archcare."""

# nuitka-project: --onefile
# nuitka-project: --onefile-tempdir-spec={CACHE_DIR}/archcare/{VERSION}
# nuitka-project: --onefile-cache-mode=cached
# nuitka-project: --include-data-dir={MAIN_DIRECTORY}/../config=archcare/config
# nuitka-project: --product-name=archcare
# nuitka-project: --reproducible=yes
# nuitka-project: --assume-yes-for-downloads
# nuitka-project: --python-flag=no_site,-O
# nuitka-project: --enable-plugins=upx
from typing import Annotated

import typer

from archcare.cli.commands import debug_app, logs_app, setup_app, task_app
from archcare.cli.context import AppContext
from archcare.services.exceptions import ConfigNotInitializedError
from archcare.utils import UserContext
from archcare.utils.output import configure_console, print_error, print_info

app = typer.Typer(
    name="archcare",
    help="Arch Linux maintenance task manager",
)

app.add_typer(task_app, name="task")
app.add_typer(setup_app, name="setup")
app.add_typer(logs_app, name="logs")
app.add_typer(debug_app, name="debug")


@app.callback()
def callback(
    ctx: typer.Context,
    devel: Annotated[
        bool,
        typer.Option(
            "--devel",
            help="Enable verbose console output (development mode)",
            is_eager=True,
        ),
    ] = False,
) -> None:
    # Constructing UserContext object
    user_ctx = UserContext.from_env()

    # Globally mute all Rich prints if running non-interactively
    configure_console(user_ctx.is_interactive)

    ctx.obj = AppContext(devel=devel, user_ctx=user_ctx)


def main():
    """
    Main entry point for the CLI.
    """
    try:
        app()
    except ConfigNotInitializedError as e:
        print_error(str(e))
        print_info("Run 'archcare setup config' to get started.")
        raise SystemExit(1) from e
    except Exception as e:
        print_error(f"Unexpected error happened: {e}")
        raise SystemExit(1) from e


if __name__ == "__main__":
    main()
