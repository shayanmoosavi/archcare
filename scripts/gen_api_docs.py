#!/usr/bin/env python
"""
Generate stub API reference documentation using Griffe and mkdocstrings autodoc syntax.

This script walks the `archcare` package (loaded from `src/`) and generates Markdown
stub files under `docs/reference/api/`. Each stub uses the `::: module.path` autodoc
syntax so that `mkdocstrings-python` can inject full API documentation at build time.

Key behaviors:
- Recursively discovers all public submodules (`walk`).
- Skips private modules (`_name`) and alias/re-export modules (`is_alias`).
- Maps `__init__` modules to `index.md` and leaf modules to `<name>.md` (`stub_path`).
- Writes minimal stub files containing only the module header and autodoc directive.
"""

from collections.abc import Iterator
from pathlib import Path

from griffe import Module, load

PACKAGE = "archcare"
OUTPUT = Path("docs/reference/api")


def walk(module: Module) -> Iterator[Module]:
    """
    Recursively yield this module and all public submodules.

    Traverses the module tree depth-first, yielding each module exactly once.
    Alias modules (re-exports) and private modules (names starting with `_`) are
    excluded from the traversal.

    Args:
        module (Module): The Griffe module to traverse.

    Yields:
        Module: This module and each public submodule discovered.
    """
    yield module
    for sub in module.modules.values():
        # Skip aliases (e.g. `from . import defaults` re-exports) and private modules
        if sub.is_alias or sub.name.startswith("_"):
            continue
        yield from walk(sub)


def stub_path(module: Module) -> Path:
    """
    Map a module to its stub page file path.

    `__init__` modules are mapped to `index.md` within their parent directory,
    while leaf modules are mapped to `<name>.md` within their parent directory.
    The module's full dotted path is split to derive the directory structure.

    Args:
        module (Module): The Griffe module to map.

    Returns:
        Path: The file path for the stub Markdown file.
    """
    # Full dotted path string: 'archcare.config.loader' -> ['config', 'loader']
    parts = module.path.split(".")[1:]
    if module.is_init_module:
        return OUTPUT.joinpath(*parts) / "index.md"
    return OUTPUT.joinpath(*parts[:-1]) / f"{parts[-1]}.md"


def main() -> None:
    """
    Generate module stub documentation for the `archcare` package.

    Loads the package using Griffe, walks all public submodules, creates stub
    Markdown files, and writes them to the configured output directory.

    Raises:
        TypeError: If Griffe fails to load the package or returns a non-Module object.
    """
    pkg = load(PACKAGE, search_paths=["src"])
    if not isinstance(pkg, Module):
        raise TypeError(f"Error in loading package: Expected a module, got {type(pkg)}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    count = 0
    for module in walk(pkg):
        mod_path = stub_path(module)
        mod_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"# `{module.path}`",
            "",
            f"::: {module.path}",
            "",
        ]
        mod_path.write_text("\n".join(lines))
        count += 1
    print(f"Generated {count} module stubs in {OUTPUT}")


if __name__ == "__main__":
    main()
