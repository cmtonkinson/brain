"""Error models and transport/domain mapping for Brain SDK calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

import grpc

from packages.brain_sdk._generated import envelope_pb2


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
    """Transport-level gRPC call failure."""

    operation: str
    status_code: grpc.StatusCode
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


def map_transport_error(*, operation: str, error: grpc.RpcError) -> BrainTransportError:
    """Map one grpc ``RpcError`` into a typed SDK transport error."""
    status = error.code() if hasattr(error, "code") else grpc.StatusCode.UNKNOWN
    detail = error.details() if hasattr(error, "details") else str(error)
    message = f"{operation} transport failure ({status.name}): {detail}"
    return BrainTransportError(
        message=message,
        operation=operation,
        status_code=status,
        retryable=status in _RETRYABLE_TRANSPORT_STATUSES,
    )


def raise_for_domain_errors(*, operation: str, errors: Sequence[object]) -> None:
    """Raise typed domain errors when response envelope ``errors`` are present."""
    if len(errors) == 0:
        return

    details = tuple(_detail_from_proto(item) for item in errors)
    error_type = _DOMAIN_CATEGORY_TO_ERROR.get(details[0].category, BrainDomainError)
    raise error_type(
        message=f"{operation} domain failure: {'; '.join(item.message for item in details)}",
        operation=operation,
        details=details,
    )


def _detail_from_proto(value: object) -> SdkErrorDetail:
    """Normalize one protobuf ``ErrorDetail`` into SDK-friendly shape."""
    return SdkErrorDetail(
        code=str(getattr(value, "code", "")),
        message=str(getattr(value, "message", "")),
        category=_category_name(int(getattr(value, "category", 0))),
        retryable=bool(getattr(value, "retryable", False)),
        metadata=dict(getattr(value, "metadata", {})),
    )


def _category_name(value: int) -> str:
    """Map protobuf error category enum values to stable lowercase names."""
    mapping = {
        envelope_pb2.ERROR_CATEGORY_VALIDATION: "validation",
        envelope_pb2.ERROR_CATEGORY_CONFLICT: "conflict",
        envelope_pb2.ERROR_CATEGORY_NOT_FOUND: "not_found",
        envelope_pb2.ERROR_CATEGORY_POLICY: "policy",
        envelope_pb2.ERROR_CATEGORY_DEPENDENCY: "dependency",
        envelope_pb2.ERROR_CATEGORY_INTERNAL: "internal",
    }
    return mapping.get(value, "unspecified")


_RETRYABLE_TRANSPORT_STATUSES: frozenset[grpc.StatusCode] = frozenset(
    {
        grpc.StatusCode.UNAVAILABLE,
        grpc.StatusCode.DEADLINE_EXCEEDED,
        grpc.StatusCode.RESOURCE_EXHAUSTED,
        grpc.StatusCode.ABORTED,
    }
)

_DOMAIN_CATEGORY_TO_ERROR = {
    "validation": BrainValidationError,
    "conflict": BrainConflictError,
    "not_found": BrainNotFoundError,
    "policy": BrainPolicyError,
    "dependency": BrainDependencyError,
    "internal": BrainInternalError,
}
