"""Public shared envelope API for Brain services."""

from .builders import empty, failure, success, with_error
from .meta import EnvelopeKind, EnvelopeMeta, new_meta
from .result import Result
from .validate import normalize_meta, utc_now, validate_meta

__all__ = [
    "EnvelopeKind",
    "EnvelopeMeta",
    "Result",
    "empty",
    "failure",
    "new_meta",
    "normalize_meta",
    "success",
    "utc_now",
    "validate_meta",
    "with_error",
]
