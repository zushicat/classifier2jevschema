"""Exceptions raised while translating between Jev and the source engine.

The route layer (Phase 4) maps these to HTTP responses (plan §2.8):

- ``JevValidationError``     -> 422 (client-side translation bug or
                                unsupported input; source engine 400)
- ``SourceUnavailableError`` -> 502 (engine unreachable / connection error /
                                timeout)
- ``SourceEngineError``      -> 502 (engine 5xx, or unparseable/incomplete
                                result)
"""


class JevValidationError(Exception):
    """Jev request cannot be served: source engine rejected the translated
    schema (HTTP 400 -> Jev 422)."""


class SourceUnavailableError(Exception):
    """The source engine could not be reached at all (connect error/timeout)."""


class SourceEngineError(Exception):
    """The source engine answered, but usefully not: 5xx or an unparseable /
    incomplete result. The local stack must never invent answers."""
