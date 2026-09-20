"""
Typer CLI interface for Archcare.

Assembles the root Typer application: mounts the four command-group sub-apps (`task`, `setup`,
`logs`, `debug`), and defines the root callback that builds the per-invocation [`AppContext`][] from
the environment (via [`UserContext.from_env`][]) and the `--devel` flag, muting Rich output when
non-interactive.

Also exposes [`main`][archcare.cli.app.main] — the console-script entry point — which catches
[`ConfigNotInitializedError`][] (→ "run `archcare setup config`" hint, exit 1) and any unexpected
exception (→ error message, exit 1).

The `nuitka-project` comments below (see source code) are build directives consumed by Nuitka when
compiling the standalone binary (`scripts/build.sh`); they are not runtime code. Note that the build
strips docstrings (`no_docstrings`), so this documentation exists for source readers and
mkdocstrings, not the shipped binary.
"""

# nuitka-project: --onefile
# nuitka-project: --onefile-tempdir-spec={CACHE_DIR}/archcare/{VERSION}
# nuitka-project: --onefile-cache-mode=cached
# nuitka-project: --product-name=archcare
# nuitka-project: --reproducible=yes
# nuitka-project: --assume-yes-for-downloads
# nuitka-project: --python-flag=-S,-O,no_docstrings
# nuitka-project: --enable-plugins=upx
from typing import Annotated

import typer

from archcare.cli.commands import debug_app, logs_app, setup_app, task_app
from archcare.cli.context import AppContext
from archcare.config import UserContext
from archcare.services.exceptions import ConfigNotInitializedError
from archcare.utils import configure_console, print_error, print_info

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
    """
    Root CLI callback: build the shared application context.

    Runs before any command: resolves the user context from the environment, configures the global
    Rich console for interactive/non-interactive output, and stores an [`AppContext`][] on `ctx.obj`
    for every command to read.

    Args:
        ctx (typer.Context): Typer context; `ctx.obj` is set here.
        devel (bool): Whether `--devel` was passed; controls console log verbosity in the context.
            Defaults to `False`.

    Side Effects:
        Configures the global Rich console and constructs the [`UserContext`][] for this invocation.
    """
    # Constructing UserContext object
    user_ctx = UserContext.from_env()

    # Globally mute all Rich prints if running non-interactively
    configure_console(user_ctx.is_interactive)

    ctx.obj = AppContext(devel=devel, user_ctx=user_ctx)


def main():
    """
    Main entry point for the CLI.

    Runs the Typer app and translates fatal errors into user-friendly messages:
    [`ConfigNotInitializedError`][] gets a "run `archcare setup config`" hint;
    anything else gets a generic unexpected-error message. Both exit with status 1.

    Raises:
        SystemExit: With code 1 on any handled fatal error (normally never surfaces to the caller —
            the process just exits).
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
