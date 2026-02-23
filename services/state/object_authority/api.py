"""gRPC adapter entrypoints for Object Authority Service."""

from __future__ import annotations

from datetime import datetime, timezone

import grpc
from brain.shared.v1 import envelope_pb2
from brain.state.v1 import object_pb2, object_pb2_grpc
from packages.brain_shared.envelope import Envelope, EnvelopeKind, EnvelopeMeta
from packages.brain_shared.errors import (
    ErrorCategory,
    ErrorDetail,
)
from services.state.object_authority.domain import (
    ObjectGetResult,
    ObjectMetadata,
    ObjectRecord,
    ObjectRef,
)
from services.state.object_authority.service import ObjectAuthorityService


class GrpcObjectAuthorityService(object_pb2_grpc.ObjectAuthorityServiceServicer):
    """gRPC servicer mapping transport requests into native OAS calls."""

    def __init__(self, service: ObjectAuthorityService) -> None:
        self._service = service

    def PutObject(
        self, request: object_pb2.PutObjectRequest, context: grpc.ServicerContext
    ) -> object_pb2.PutObjectResponse:
        result = self._service.put_object(
            meta=_meta_from_proto(request.metadata),
            content=request.payload.content,
            extension=request.payload.extension,
            content_type=request.payload.content_type,
            original_filename=request.payload.original_filename,
            source_uri=request.payload.source_uri,
        )
        _abort_for_transport_errors(context=context, result=result)
        return object_pb2.PutObjectResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=_record_to_proto(
                None if result.payload is None else result.payload.value
            ),
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def GetObject(
        self, request: object_pb2.GetObjectRequest, context: grpc.ServicerContext
    ) -> object_pb2.GetObjectResponse:
        result = self._service.get_object(
            meta=_meta_from_proto(request.metadata),
            object_key=request.payload.object_key,
        )
        _abort_for_transport_errors(context=context, result=result)
        return object_pb2.GetObjectResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=_get_result_to_proto(
                None if result.payload is None else result.payload.value
            ),
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def StatObject(
        self, request: object_pb2.StatObjectRequest, context: grpc.ServicerContext
    ) -> object_pb2.StatObjectResponse:
        result = self._service.stat_object(
            meta=_meta_from_proto(request.metadata),
            object_key=request.payload.object_key,
        )
        _abort_for_transport_errors(context=context, result=result)
        return object_pb2.StatObjectResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=_record_to_proto(
                None if result.payload is None else result.payload.value
            ),
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def DeleteObject(
        self,
        request: object_pb2.DeleteObjectRequest,
        context: grpc.ServicerContext,
    ) -> object_pb2.DeleteObjectResponse:
        result = self._service.delete_object(
            meta=_meta_from_proto(request.metadata),
            object_key=request.payload.object_key,
        )
        _abort_for_transport_errors(context=context, result=result)
        return object_pb2.DeleteObjectResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=bool(result.payload.value) if result.payload is not None else False,
            errors=[_error_to_proto(item) for item in result.errors],
        )


def _abort_for_transport_errors(
    *,
    context: grpc.ServicerContext,
    result: Envelope[object],
) -> None:
    """Abort gRPC transport for dependency/internal category failures."""
    dependency_messages = [
        error.message
        for error in result.errors
        if error.category == ErrorCategory.DEPENDENCY
    ]
    if dependency_messages:
        context.abort(grpc.StatusCode.UNAVAILABLE, "; ".join(dependency_messages))

    internal_messages = [
        error.message
        for error in result.errors
        if error.category == ErrorCategory.INTERNAL
    ]
    if internal_messages:
        context.abort(grpc.StatusCode.INTERNAL, "; ".join(internal_messages))


def _meta_from_proto(meta: envelope_pb2.EnvelopeMeta) -> EnvelopeMeta:
    """Convert protobuf metadata into canonical envelope metadata."""
    if meta.timestamp.seconds == 0 and meta.timestamp.nanos == 0:
        timestamp = datetime.now(timezone.utc)
    else:
        timestamp = datetime.fromtimestamp(
            meta.timestamp.seconds + (meta.timestamp.nanos / 1_000_000_000),
            tz=timezone.utc,
        )
    return EnvelopeMeta(
        envelope_id=meta.envelope_id,
        trace_id=meta.trace_id,
        parent_id=meta.parent_id,
        timestamp=timestamp,
        kind=_kind_from_proto(meta.kind),
        source=meta.source,
        principal=meta.principal,
    )


def _meta_to_proto(meta: EnvelopeMeta) -> envelope_pb2.EnvelopeMeta:
    """Convert canonical metadata into protobuf shape."""
    seconds = int(meta.timestamp.timestamp())
    nanos = int((meta.timestamp.timestamp() - seconds) * 1_000_000_000)
    return envelope_pb2.EnvelopeMeta(
        envelope_id=meta.envelope_id,
        trace_id=meta.trace_id,
        parent_id=meta.parent_id,
        kind=_kind_to_proto(meta.kind),
        timestamp={"seconds": seconds, "nanos": nanos},
        source=meta.source,
        principal=meta.principal,
    )


def _kind_from_proto(kind: int) -> EnvelopeKind:
    """Map protobuf envelope kind enum to canonical kind."""
    if kind == envelope_pb2.ENVELOPE_KIND_COMMAND:
        return EnvelopeKind.COMMAND
    if kind == envelope_pb2.ENVELOPE_KIND_EVENT:
        return EnvelopeKind.EVENT
    if kind == envelope_pb2.ENVELOPE_KIND_RESULT:
        return EnvelopeKind.RESULT
    if kind == envelope_pb2.ENVELOPE_KIND_STREAM:
        return EnvelopeKind.STREAM
    return EnvelopeKind.UNSPECIFIED


def _kind_to_proto(kind: EnvelopeKind) -> int:
    """Map canonical envelope kind to protobuf enum value."""
    if kind == EnvelopeKind.COMMAND:
        return envelope_pb2.ENVELOPE_KIND_COMMAND
    if kind == EnvelopeKind.EVENT:
        return envelope_pb2.ENVELOPE_KIND_EVENT
    if kind == EnvelopeKind.RESULT:
        return envelope_pb2.ENVELOPE_KIND_RESULT
    if kind == EnvelopeKind.STREAM:
        return envelope_pb2.ENVELOPE_KIND_STREAM
    return envelope_pb2.ENVELOPE_KIND_UNSPECIFIED


def _error_to_proto(error: ErrorDetail) -> envelope_pb2.ErrorDetail:
    """Convert one domain error detail to protobuf."""
    return envelope_pb2.ErrorDetail(
        code=error.code,
        message=error.message,
        category=_error_category_to_proto(error.category),
        retryable=error.retryable,
        metadata=dict(error.metadata),
    )


def _error_category_to_proto(category: ErrorCategory) -> int:
    """Map domain error category to protobuf enum constant."""
    mapping = {
        ErrorCategory.VALIDATION: envelope_pb2.ERROR_CATEGORY_VALIDATION,
        ErrorCategory.NOT_FOUND: envelope_pb2.ERROR_CATEGORY_NOT_FOUND,
        ErrorCategory.CONFLICT: envelope_pb2.ERROR_CATEGORY_CONFLICT,
        ErrorCategory.POLICY: envelope_pb2.ERROR_CATEGORY_POLICY,
        ErrorCategory.DEPENDENCY: envelope_pb2.ERROR_CATEGORY_DEPENDENCY,
        ErrorCategory.INTERNAL: envelope_pb2.ERROR_CATEGORY_INTERNAL,
    }
    return mapping.get(category, envelope_pb2.ERROR_CATEGORY_UNSPECIFIED)


def _ref_to_proto(value: ObjectRef | None) -> object_pb2.ObjectRef:
    """Convert one domain object reference to protobuf."""
    if value is None:
        return object_pb2.ObjectRef()
    return object_pb2.ObjectRef(object_key=value.object_key)


def _metadata_to_proto(value: ObjectMetadata | None) -> object_pb2.ObjectMetadata:
    """Convert one domain object metadata value to protobuf."""
    if value is None:
        return object_pb2.ObjectMetadata()

    return object_pb2.ObjectMetadata(
        digest_algorithm=value.digest_algorithm,
        digest_version=value.digest_version,
        digest_hex=value.digest_hex,
        extension=value.extension,
        content_type=value.content_type,
        size_bytes=value.size_bytes,
        original_filename=value.original_filename,
        source_uri=value.source_uri,
        created_at={
            "seconds": int(value.created_at.timestamp()),
            "nanos": int((value.created_at.timestamp() % 1) * 1_000_000_000),
        },
        updated_at={
            "seconds": int(value.updated_at.timestamp()),
            "nanos": int((value.updated_at.timestamp() % 1) * 1_000_000_000),
        },
    )


def _record_to_proto(value: ObjectRecord | None) -> object_pb2.ObjectRecord:
    """Convert one domain object record to protobuf."""
    if value is None:
        return object_pb2.ObjectRecord()
    return object_pb2.ObjectRecord(
        ref=_ref_to_proto(value.ref),
        metadata=_metadata_to_proto(value.metadata),
    )


def _get_result_to_proto(value: ObjectGetResult | None) -> object_pb2.GetObjectResult:
    """Convert one domain get-object result into protobuf payload."""
    if value is None:
        return object_pb2.GetObjectResult()
    return object_pb2.GetObjectResult(
        object=_record_to_proto(value.object),
        content=value.content,
    )
