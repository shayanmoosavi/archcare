# Archcare dev task runner
#
# `just` (no args) runs the first recipe (`sync`).
# `just --list` shows all available recipes.
# Install: https://github.com/casey/just#installation
#
# No venv activation is needed: uv-based recipes run through `uv`, and the
# clean recipes are plain `rm`.

# Create/refresh the uv environment with all dependency groups
sync:
    uv sync --all-groups

# Lint + format check (same commands and order as CI)
lint:
    uv run ruff check .
    uv run ruff format --check .

# Auto-format code and docstring code blocks
format:
    uv run ruff format .

# Static type check
type-check:
    uv run ty check

# Run the full CI gate sequence: lint -> tests -> type check
check: lint test
    uv run ty check

# Run the full test suite
test:
    uv run pytest

# Run unit tests only
test-unit:
    uv run pytest tests/unit

# Run integration tests only
test-integration:
    uv run pytest tests/integration

# Doctest the modules
doctest:
    uv run pytest --doctest-modules src/archcare

# Regenerate API reference stubs, then build the docs site (strict)
docs-build:
    uv run python scripts/gen_api_docs.py
    uv run zensical build --strict

# Serve the docs site locally with live reload
docs-serve:
    uv run zensical serve

# Build the standalone Nuitka binary into dist/
build:
    uv sync --group build
    uv run scripts/build.sh

# Create a commit following the commitizen conventions
commit:
    uv run cz commit

# --- Cleanup ------------------------------------------------------------

# Remove generated build artifacts (dist/, site/, docs API stubs)
clean:
    rm -rf dist site docs/reference/api

# Remove caches and coverage data
clean-cache:
    rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage
