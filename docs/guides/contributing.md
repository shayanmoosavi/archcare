# Contributing

**Audience:** a new contributor past the [README](https://github.com/shayanmoosavi/archcare#readme).
Adding a maintenance task has its own guide — [Adding a new task](adding-a-task.md) — so this page
covers everything else: environment setup, project layout, the layering contract, the quality gates
every change must pass, and how commits, pull requests, and releases work.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) — the project management tool. On Arch Linux (btw 😎):
  `sudo pacman -S uv`
- git
- Python 3.13 or 3.14 (`requires-python = ">=3.13,<3.15"` — uv manages the interpreter itself, so
  you don't need to install it)
- An Arch Linux machine is **recommended**, not required. The tool's domain is Arch-specific, but
  the test suite is hermetic: integration tests run the real CLI against a temp directory (see the
  `archcare_home` fixture in `tests/integration/conftest.py`) and mock the only OS boundary, so the
  full suite passes on any Linux with Python 3.13+.

## Development environment

Fork the repository, clone your fork, and install all dependency groups:

```bash
git clone https://github.com/<you>/archcare.git
cd archcare
uv sync --all-groups
```

The groups are defined in `pyproject.toml`; each exists for a reason:

| Group   | Contents                                              | When you need it                                  |
| ------- | ----------------------------------------------------- | ------------------------------------------------- |
| `dev`   | ruff, ty, prek, commitizen (includes `docs` + `test`) | Always — `--all-groups` installs everything below |
| `test`  | pytest, pytest-cov, pytest-mock                       | Running the test suite                            |
| `docs`  | mkdocs-material, mkdocstrings, mkdocs plugins         | Building or serving this documentation site       |
| `build` | nuitka, patchelf                                      | Producing the standalone binary (maintainers)     |

!!! warning

    patchelf is **required** for standalone build on Linux.

Sanity-check the environment:

```bash
uv run pytest
# expected: all tests pass
```

## Project layout

Archcare is strictly layered — `cli/` → `services/` → `core/` + `config/` → `tasks/` + `utils/`.
The [Architecture Overview](../architecture/index.md) is the authoritative tour; don't rest on
this page's one-line summary:

| Layer | Modules in `src/archcare/` | Responsibility                                         |
| ----- | -------------------------- | ------------------------------------------------------ |
| CLI   | `cli/`                     | Typer commands, Rich rendering, port implementations   |
| SVC   | `services/`                | One service per command group; response DTOs           |
| TASKS | `tasks/`                   | One module per maintenance task                        |
| CORE  | `core/`                    | `BaseTask` pipeline, executor, registry, ports, models |
| CONF  | `config/`                  | Pydantic models, TOML/JSON loading, state, logging     |
| UTILS | `utils/`                   | The OS boundary — subprocess, hardware, pacman         |

## The layering rule

There is exactly one hard rule, restated from the overview:

> **`core/` and `config/` never import from `cli/` or `services/`.**

Everything those layers need from the outside world arrives as constructor arguments or through the
[port protocols](../architecture/registry-and-ports.md). This is what keeps the engine
presentation-agnostic — and it is enforced by review, not by tooling, so check your imports before
pushing:

```bash
# Get every match with exact line numbers
grep -rnE "(from|import) archcare\.(cli|services)" \
    src/archcare/core src/archcare/config
# expected: no output (grep exits 1)
```

or by using `ruff analyze graph` tool:

```bash
# Get every match in the generated JSON graph
uv run ruff analyze graph \
    src/archcare/config src/archcare/core \
    | grep -E "(cli|services)"
# expected: no output (grep exits 1)
```

Two spots routinely trip up newcomers — neither is a violation:

- The **ports** (`TaskInteraction`, `TaskProgress`, `TaskDetailFormatter`) are _defined_ in
  `core/` and _implemented_ in `cli/`. The import direction is `cli → core` — downward — because
  `core/` depends only on the duck-typed protocol it declares, never on any concrete
  implementation. This dependency inversion is not a bend in the rule; it is what makes the rule
  sustainable (see [Registry, ports & extensibility](../architecture/registry-and-ports.md)).
- Every layer defines its own exceptions, all rooted in
  [`ArchcareError`][archcare.exceptions.ArchcareError] in `archcare/exceptions.py`. That module
  sits at the package root, outside `core/` and `config/`, so every layer's import of it is again
  a downward import into a shared sink — layers never reach into each other's _business_ modules.

## Code style and static checks

[Ruff](https://docs.astral.sh/ruff) handles both linting and formatting, configured in
`pyproject.toml`:

- `line-length = 100`
- Lint rules: `E` (pycodestyle), `F` (Pyflakes), `I` (import sorting), `UP` (pyupgrade),
  `B` (flake8-bugbear)
- `docstring-code-format = true` — code examples inside docstrings are auto-formatted, so write
  them as if `ruff format` will run over them (it will)

[ty](https://docs.astral.sh/ty) is the type checker. The gate CI pipeline actually runs, in order:

```bash
uv run ruff check && uv run ruff format --check && uv run pytest && uv run ty check
```

Run that sequence before every push — it is exactly what `.github/workflows/ci.yml` runs, so green
locally means green in CI.

!!! note "pytest configuration lives in `[tool.pytest]`"

    pytest options are set under `[tool.pytest]` in `pyproject.toml` — the native TOML format
    (native types, supported since
    [pytest 9.0](https://docs.pytest.org/en/stable/reference/customize.html); the pre-9.0 style was
    the INI-flavored `[tool.pytest.ini_options]`). Currently it applies
    `addopts = ["--import-mode=importlib"]` to every run. Add options there, not to a `pytest.ini`.

## Pre-commit hooks

Archcare uses [prek](https://prek.j178.dev) — a Rust drop-in replacement for
[pre-commit](https://pre-commit.com/) — configured in `prek.toml`. Install the shims once per clone:

```bash
uv run prek install --hook-type commit-msg --hook-type pre-push
```

What runs automatically on each commit:

- Whitespace and line-ending fixers (`trailing-whitespace` — which deliberately exempts `.md`
  trailing linebreaks — `mixed-line-ending --fix=auto`, `end-of-file-fixer`)
- Test-naming convention (`name-tests-test --pytest-test-first` — test files start with `test_`)
- Merge-conflict markers, YAML/TOML/JSON validity, shebang executability checks
- `no-commit-to-branch --branch=main` — direct commits to `main` are blocked by design
- Local hooks: `ruff format .` and `ruff check --select=I --fix` (import sorting)
- The `commitizen` hook validates your commit message (see below)

On `pre-push`: `commitizen-branch` validates every message in the pushed range.

To run everything on demand:

```bash
uv run prek run --all-files
uv run prek list             # see the configured hooks
```

## Testing philosophy

The suite is split by intent, not just by directory:

- **Unit tests** (`tests/unit/`) mirror `src/archcare/` 1:1 and mock at precise boundaries — real
  Pydantic models over bare mocks wherever construction is cheap, `mocker.patch.object` over
  stacked `@patch` decorators, and specced mocks (`MagicMock(spec=X)`) so an attribute typo is an
  attribute error, not a silently-passing no-op.
- **Integration tests** (`tests/integration/`) invoke the real CLI via Typer's `CliRunner`, build a
  real `AppContext`, and do real file I/O under `tmp_path` (the `archcare_home` fixture redirects
  all config/state paths there). The _only_ things ever mocked are the OS boundary —
  [`run_command`][archcare.utils.system.run_command] and
  [`run_command_with_sudo`][archcare.utils.system.run_command_with_sudo] from
  [`archcare.utils.system`][archcare.utils.system] — and desktop notifications.

Shared fixtures live in `tests/unit/conftest.py` (reusable `TaskConfig` / `AppState` builders) and
`tests/integration/conftest.py` (`archcare_home`). Put a fixture in the narrowest conftest that
still serves every consumer.

This combination has caught real bugs unit tests alone missed — check `git log` for examples where
a mocked unit test passed while the real wiring was broken. When you add behavior, prefer one
integration test exercising the real path over many integration tests re-testing unit-covered
logic; the [adding-a-task guide](adding-a-task.md#step-7-test-it) shows the worked pattern.

```bash
uv run pytest                    # full suite
uv run pytest tests/unit         # unit only
uv run pytest tests/integration  # integration only
uv run pytest --cov              # with coverage
```

Doctest-style examples in docstrings count as tests too — see
[Documentation conventions](#documentation-conventions) for the bar they must meet.

## Documentation conventions

Documentation lives in three places, each with its own bar:

- **The README** — first contact: what the tool is, install, quick start.
- **This site** — architecture, guides, and reference: the long form.
- **Docstrings** — the API reference: every public class, function, and method documents itself,
  and mkdocstrings renders it into the reference pages. Keep docstring prose thorough enough that
  the API reference stands alone.

### Docstring style: Google

Docstrings follow the
[Google style](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings):
`Attributes:` sections on classes and dataclasses, `Args:`/`Returns:`/`Raises:` on functions and
methods, and `Examples:` for behavior best shown by example. Cross-reference other API objects
with mkdocstrings syntax — ``[`TaskResult`][]`` in module docstrings (if the module imports it), or
the explicit</br> ``[`TaskResult`][archcare.core.models.TaskResult]`` form elsewhere — rather than
backticks, so the reference pages link up automatically.

Because `merge_init_into_class` is set in `mkdocs.yml`, `__init__` docstrings render as part of
the class docstring — document constructor arguments there (see
[Registry, ports & extensibility](../architecture/registry-and-ports.md)).

### Docstring examples are doctests

Examples in docstrings are written as real
[doctests](https://docs.python.org/3/library/doctest.html) and are part of the contract:
documented behavior must be **executable and passing**. The default suite does not collect them
(see the `[tool.pytest]` note above), so run them explicitly:

```bash
uv run pytest --doctest-modules src/archcare
```

If an example stops passing, the docstring lies — fix the docstring or the code; never edit one to
match the other without deciding which is wrong. Keep examples deterministic (no timestamps, no
system state), and remember `docstring-code-format = true` means `ruff format` will reformat
them.

### CLI help text: `help=`, not docstrings

Typer takes command help from `help=` parameters — on `typer.Typer(help=...)`,
`typer.Argument(help=...)`, and `typer.Option(help=...)` — **not** from command-function
docstrings. The separation is deliberate: the standalone binary is compiled with Nuitka using
`--python-flag=no_docstrings`, which strips docstrings from the shipped `archcare` executable
while `help=` arguments survive compilation. So:

- **`help=`** is what users see via `archcare <command> --help` — write it user-facing.
- **The docstring** is what contributors see in the API reference — write it contributor-facing.

## Commit conventions

Archcare uses [commitizen](https://commitizen-tools.github.io/commitizen/) with conventional
commits — write the message with the interactive helper:

```bash
uv run cz commit
```

Scopes name the layer or module touched (`core`, `config`, `loader`, `commands`, `utils`, ...).
Real examples from `CHANGELOG.md`:

```text
fix(core): fix wrong error message for an unregistered task
refactor(config): move enums to a dedicated module and update imports
refactor: move base task to core layer for architectural consistency
```

Message validity is not enforced by review alone — the prek `commitizen` hook rejects malformed
messages at commit time, and `commitizen-branch` re-checks the range on push.

## Pull request workflow

1. Branch from `dev`:

    ```bash
    git checkout dev && git pull
    git checkout -b feat/my-change  # For new features
    git checkout -b fix/my-change   # For bug fixes
    git checkout -b refactor/my-change  # For refactoring
    ```

2. Make your change and add tests (see [Testing philosophy](#testing-philosophy)).
3. Run the full gate:

    ```bash
    uv run ruff check && uv run ruff format --check && uv run pytest && uv run ty check
    ```

4. Commit with `uv run cz commit` (the prek hooks will validate as you go).
5. Push and open a pull request targeting `dev` — `main` is reserved for releases only.
6. Wait for CI to pass and a maintainer to review and merge.

Keep pull requests focused: one behavior or fix per PR, tests included. If documentation (README
or this site) is affected by your change, update it in the same PR and verify the site still
builds strictly:

```bash
uv run mkdocs build --strict
# expected: build completes with no warnings
```

## Releases (maintainers)

Releases are tag-driven and automated by `.github/workflows/release.yml`. The flow:

1. **Bump the version** — commitizen reads the version from `pyproject.toml` (`version_provider =
"pep621"`), writes `CHANGELOG.md` (`update_changelog_on_bump`), runs `uv lock`
   (`pre_bump_hooks`), and creates the GPG-signed annotated tag `v$version` (`tag_format`,
   `annotated_tag`, `gpg_sign` — all set in `[tool.commitizen]`):

    ```bash
    uv run cz bump          # or: uv run cz bump --prerelease (for prereleases)
    git push --follow-tags
    ```

2. **Tag guard** — the workflow verifies the tag matches the project version, canonicalizing both
   through PEP 440 (`v0.1.0-rc1` → `0.1.0rc1`), and fails early on a mismatch.
3. **Verify** — the full test suite and `ty check` run again on the tag.
4. **Build** — `scripts/build.sh` produces the standalone binary with
   [Nuitka](https://nuitka.net/) (build directives live as `# nuitka-project:` comments at the top
   of [`cli/app.py`][archcare.cli.app]): onefile with a cached tempdir spec (only for local builds),
   docstrings stripped (`--python-flag=-S,-O,no_docstrings`), reproducible, compressed via the UPX
   plugin. Clang compiler is preferred when present; the workflow pins `clang-22`.
   A `build-info.txt` records the toolchain.
5. **Quality gates** — the binary must run (`./dist/archcare --help`) and must not exceed a
   **45 MB** size threshold (for CLI).
6. **Sign and publish** — the sha256 checksum is GPG-signed (`archcare.sha256.asc`), everything is
   packed into `archcare-<VERSION>-linux-x86_64.tar.gz`, and a **draft** GitHub Release is created
   with generated notes — publish it manually after review.

!!! note "The docs site is not part of the release artifact"

    The documentation site builds separately via `uv run mkdocs build --strict` and is never packed
    into the release archive. `release.yml` does not build docs at all.

## Where to ask questions

Open an [issue](https://github.com/shayanmoosavi/archcare/issues) for bug reports, feature ideas,
and questions about contributing. For usage help, the README and this site's
[architecture pages](../architecture/index.md) are the first stop.

## Related pages

- [Architecture Overview](../architecture/index.md) — the layered design and the philosophy
  behind it.
- [Registry, Ports & Extensibility](../architecture/registry-and-ports.md) — the port protocols
  the layering rule leans on.
- [Adding a new task](adding-a-task.md) — the step-by-step guide this page defers to.
- [Configuration & state](../architecture/configuration.md) — where config and state files live
  when you're debugging a test failure.
