"""Error models and transport/domain mapping for Brain SDK calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence


@dataclass(frozen=True, slots=True)
class SdkErrorDetail:
    """One normalized domain error returned in a response envelope."""

    code: str
    message: str
    category: str
    retryable: bool = False
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class BrainSdkError(Exception):
    """Base error type for Brain SDK failures."""

    message: str

    def __str__(self) -> str:
        """Return human-readable error message."""
        return self.message


@dataclass(frozen=True)
class BrainTransportError(BrainSdkError):
    """Transport-level HTTP call failure."""

    operation: str
    status_code: int
    retryable: bool = False


@dataclass(frozen=True)
class BrainDomainError(BrainSdkError):
    """Domain-level envelope error from a successful transport call."""

    operation: str
    details: tuple[SdkErrorDetail, ...] = ()


@dataclass(frozen=True)
class BrainValidationError(BrainDomainError):
    """Validation-category domain failure."""


@dataclass(frozen=True)
class BrainConflictError(BrainDomainError):
    """Conflict-category domain failure."""


@dataclass(frozen=True)
class BrainNotFoundError(BrainDomainError):
    """Not-found category domain failure."""


@dataclass(frozen=True)
class BrainPolicyError(BrainDomainError):
    """Policy-category domain failure."""


@dataclass(frozen=True)
class BrainDependencyError(BrainDomainError):
    """Dependency-category domain failure."""


@dataclass(frozen=True)
class BrainInternalError(BrainDomainError):
    """Internal-category domain failure."""


def map_transport_error(
    *, operation: str, status_code: int, message: str, retryable: bool = False
) -> BrainTransportError:
    """Map one HTTP error into a typed SDK transport error."""
    return BrainTransportError(
        message=f"{operation} transport failure (HTTP {status_code}): {message}",
        operation=operation,
        status_code=status_code,
        retryable=retryable,
    )


def raise_for_domain_errors(*, operation: str, errors: Sequence[object]) -> None:
    """Raise typed domain errors when response envelope ``errors`` are present."""
    if len(errors) == 0:
        return

    details = tuple(_detail_from_dict(item) for item in errors)
    error_type = _DOMAIN_CATEGORY_TO_ERROR.get(details[0].category, BrainDomainError)
    raise error_type(
        message=f"{operation} domain failure: {'; '.join(item.message for item in details)}",
        operation=operation,
        details=details,
    )


def _detail_from_dict(value: object) -> SdkErrorDetail:
    """Normalize one error detail dict or object into SDK-friendly shape."""
    if isinstance(value, dict):
        return SdkErrorDetail(
            code=str(value.get("code", "")),
            message=str(value.get("message", "")),
            category=str(value.get("category", "unspecified")),
            retryable=bool(value.get("retryable", False)),
            metadata=dict(value.get("metadata", {})),
        )
    return SdkErrorDetail(
        code=str(getattr(value, "code", "")),
        message=str(getattr(value, "message", "")),
        category=str(getattr(value, "category", "unspecified")),
        retryable=bool(getattr(value, "retryable", False)),
        metadata=dict(getattr(value, "metadata", {})),
    )


_DOMAIN_CATEGORY_TO_ERROR = {
    "validation": BrainValidationError,
    "conflict": BrainConflictError,
    "not_found": BrainNotFoundError,
    "policy": BrainPolicyError,
    "dependency": BrainDependencyError,
    "internal": BrainInternalError,
}
