"""
Shared base exception for all domain-specific errors raised anywhere in archcare.

Every layer (`core`, `config`, `services`) defines its own exceptions rooted in
[`ArchcareError`][], so callers can catch any archcare-specific failure with a single
`except ArchcareError` while still handling specific cases with the layer-local classes.

See Also:
    - [`archcare.core.exceptions`][]: Core-layer exception hierarchy
    - [`archcare.config.exceptions`][]: Config-layer exception hierarchy
    - [`archcare.services.exceptions`][]: Service-layer exception hierarchy
"""


class ArchcareError(Exception):
    """
    Base class for all domain exceptions raised anywhere in archcare.

    Deliberately minimal (no extra attributes); layer-specific hierarchies subclass it and add their
    own context. Note that some core/config exceptions also subclass `ValueError` on purpose (so
    Pydantic validators re-raise them) — see those modules for details.
    """
