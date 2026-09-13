# Guides

**Audience:** task authors and contributors. This site has three layers — the
[architecture pages](../architecture/index.md) explain _why_ the system is shaped the way it
is, the guides here show _how_ to work within it, and the
[API reference](../autoapi/archcare/index.md) documents the _exact shapes_ of every piece.

!!! tip "Just want to use Archcare?"

    Installation, quick start, and command usage live in the
    [README](https://github.com/shayanmoosavi/archcare#readme). These guides are for changing
    the tool, not running it.

## What's in this section

<div class="grid cards" markdown>

- :material-plus-circle:{ .lg .middle } **Adding a new task**

    ***

    A complete, step-by-step guide to implementing, registering, formatting,
    and testing a new maintenance task.

    [:material-book-outline: Follow the guide](adding-a-task.md){ .md-button .md-button--primary }

- :material-account-group:{ .lg .middle } **Contributing**

    ***

    Development setup, the layering contract, the testing philosophy, the
    quality gates, and commit, PR, and release conventions.

    [:fontawesome-regular-handshake: Start contributing](contributing.md){ .md-button .md-button--primary }

</div>

## The 5-minute path

1. Fork the repository and run `uv sync --all-groups` — see
   [Development environment](contributing.md#development-environment).
2. Run `uv run pytest` and confirm the suite is green — see
   [Testing philosophy](contributing.md#testing-philosophy).
3. Internalize [the layering rule](contributing.md#the-layering-rule) — there is exactly one
   hard rule, and everything else follows from it.
4. Implement your change, guided by the
   [adding-a-task guide](adding-a-task.md) if it is a new maintenance task.
5. Commit with `uv run cz commit` — see
   [Commit conventions](contributing.md#commit-conventions).

## Related pages

- [Architecture Overview](../architecture/index.md) — the philosophy behind the how.
- [API reference](../autoapi/archcare/index.md) — auto-generated from the source docstrings.
