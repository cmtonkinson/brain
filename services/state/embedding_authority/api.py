"""gRPC adapter entrypoints for Embedding Authority Service (EAS)."""

from __future__ import annotations

from datetime import datetime, timezone

import grpc
from brain.shared.v1 import envelope_pb2
from brain.state.v1 import embedding_pb2, embedding_pb2_grpc
from packages.brain_shared.envelope import EnvelopeKind, EnvelopeMeta, Result
from packages.brain_shared.errors import ErrorCategory, ErrorDetail
from services.state.embedding_authority.domain import (
    EmbeddingMatch,
    EmbeddingRecord,
    EmbeddingRef,
)
from services.state.embedding_authority.service import EmbeddingAuthorityService


class GrpcEmbeddingAuthorityService(
    embedding_pb2_grpc.EmbeddingAuthorityServiceServicer
):
    """gRPC servicer that delegates to the in-process EAS API contract."""

    def __init__(self, service: EmbeddingAuthorityService) -> None:
        """Create a gRPC adapter around an in-process EAS implementation."""
        self._service = service

    def UpsertEmbedding(
        self,
        request: embedding_pb2.UpsertEmbeddingRequest,
        context: grpc.ServicerContext,
    ) -> embedding_pb2.UpsertEmbeddingResponse:
        """Map gRPC UpsertEmbedding to service.upsert_embedding()."""
        result = self._service.upsert_embedding(
            meta=_meta_from_proto(request.meta),
            ref=_ref_from_proto(request.ref),
            vector=tuple(request.vector),
            model=request.model,
            metadata=dict(request.metadata),
        )
        _abort_for_transport_errors(context=context, result=result)
        return embedding_pb2.UpsertEmbeddingResponse(
            meta=_meta_to_proto(result.metadata),
            embedding=_record_to_proto(result.payload),
            errors=[_error_to_proto(error) for error in result.errors],
        )

    def GetEmbedding(
        self,
        request: embedding_pb2.GetEmbeddingRequest,
        context: grpc.ServicerContext,
    ) -> embedding_pb2.GetEmbeddingResponse:
        """Map gRPC GetEmbedding to service.get_embedding()."""
        result = self._service.get_embedding(
            meta=_meta_from_proto(request.meta),
            ref=_ref_from_proto(request.ref),
        )
        _abort_for_transport_errors(context=context, result=result)
        found = result.payload is not None
        return embedding_pb2.GetEmbeddingResponse(
            meta=_meta_to_proto(result.metadata),
            found=found,
            embedding=_record_to_proto(result.payload),
            errors=[_error_to_proto(error) for error in result.errors],
        )

    def DeleteEmbedding(
        self,
        request: embedding_pb2.DeleteEmbeddingRequest,
        context: grpc.ServicerContext,
    ) -> embedding_pb2.DeleteEmbeddingResponse:
        """Map gRPC DeleteEmbedding to service.delete_embedding()."""
        result = self._service.delete_embedding(
            meta=_meta_from_proto(request.meta),
            ref=_ref_from_proto(request.ref),
            missing_ok=request.missing_ok,
        )
        _abort_for_transport_errors(context=context, result=result)
        return embedding_pb2.DeleteEmbeddingResponse(
            meta=_meta_to_proto(result.metadata),
            deleted=bool(result.payload),
            errors=[_error_to_proto(error) for error in result.errors],
        )

    def SearchEmbeddings(
        self,
        request: embedding_pb2.SearchEmbeddingsRequest,
        context: grpc.ServicerContext,
    ) -> embedding_pb2.SearchEmbeddingsResponse:
        """Map gRPC SearchEmbeddings to service.search_embeddings()."""
        result = self._service.search_embeddings(
            meta=_meta_from_proto(request.meta),
            namespace=request.namespace,
            query_vector=tuple(request.query_vector),
            limit=request.limit,
            model=request.model,
        )
        _abort_for_transport_errors(context=context, result=result)
        matches: list[embedding_pb2.EmbeddingMatch] = []
        if result.payload is not None:
            matches = [_match_to_proto(match) for match in result.payload]
        return embedding_pb2.SearchEmbeddingsResponse(
            meta=_meta_to_proto(result.metadata),
            matches=matches,
            errors=[_error_to_proto(error) for error in result.errors],
        )


def register_embedding_authority_service(
    server: grpc.Server,
    service: EmbeddingAuthorityService,
) -> None:
    """Attach an EAS implementation to a gRPC server via adapter mapping."""
    embedding_pb2_grpc.add_EmbeddingAuthorityServiceServicer_to_server(
        GrpcEmbeddingAuthorityService(service=service),
        server,
    )


def _meta_from_proto(meta: envelope_pb2.EnvelopeMeta) -> EnvelopeMeta:
    """Convert protobuf envelope metadata into native metadata."""
    timestamp = meta.timestamp.ToDatetime(tzinfo=timezone.utc)
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
    """Convert native envelope metadata into protobuf metadata."""
    message = envelope_pb2.EnvelopeMeta(
        envelope_id=meta.envelope_id,
        trace_id=meta.trace_id,
        parent_id=meta.parent_id,
        kind=_kind_to_proto(meta.kind),
        source=meta.source,
        principal=meta.principal,
    )
    message.timestamp.FromDatetime(_utc(meta.timestamp))
    return message


def _error_to_proto(error: ErrorDetail) -> envelope_pb2.ErrorDetail:
    """Convert native error details into protobuf error details."""
    return envelope_pb2.ErrorDetail(
        code=error.code,
        message=error.message,
        category=_error_category_to_proto(error.category),
        retryable=error.retryable,
        metadata=dict(error.metadata),
    )


def _ref_from_proto(ref: embedding_pb2.EmbeddingRef) -> EmbeddingRef:
    """Convert protobuf embedding reference into native reference."""
    return EmbeddingRef(namespace=ref.namespace, key=ref.key)


def _ref_to_proto(ref: EmbeddingRef) -> embedding_pb2.EmbeddingRef:
    """Convert native embedding reference into protobuf reference."""
    return embedding_pb2.EmbeddingRef(namespace=ref.namespace, key=ref.key)


def _record_to_proto(record: EmbeddingRecord | None) -> embedding_pb2.EmbeddingRecord:
    """Convert native embedding record into protobuf embedding record."""
    if record is None:
        return embedding_pb2.EmbeddingRecord()

    message = embedding_pb2.EmbeddingRecord(
        ref=_ref_to_proto(record.ref),
        vector=list(record.vector),
        model=record.model,
        dimensions=record.dimensions,
        metadata=dict(record.metadata),
    )
    message.created_at.FromDatetime(_utc(record.created_at))
    message.updated_at.FromDatetime(_utc(record.updated_at))
    return message


def _match_to_proto(match: EmbeddingMatch) -> embedding_pb2.EmbeddingMatch:
    """Convert native embedding match into protobuf embedding match."""
    return embedding_pb2.EmbeddingMatch(
        ref=_ref_to_proto(match.ref),
        score=match.score,
        metadata=dict(match.metadata),
    )


def _utc(value: datetime) -> datetime:
    """Normalize datetimes for protobuf Timestamp conversion."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _kind_from_proto(kind: envelope_pb2.EnvelopeKind) -> EnvelopeKind:
    """Convert protobuf envelope kind enum into shared domain enum."""
    mapping = {
        envelope_pb2.ENVELOPE_KIND_UNSPECIFIED: EnvelopeKind.UNSPECIFIED,
        envelope_pb2.ENVELOPE_KIND_COMMAND: EnvelopeKind.COMMAND,
        envelope_pb2.ENVELOPE_KIND_EVENT: EnvelopeKind.EVENT,
        envelope_pb2.ENVELOPE_KIND_RESULT: EnvelopeKind.RESULT,
        envelope_pb2.ENVELOPE_KIND_STREAM: EnvelopeKind.STREAM,
    }
    return mapping.get(kind, EnvelopeKind.UNSPECIFIED)


def _kind_to_proto(kind: EnvelopeKind) -> envelope_pb2.EnvelopeKind:
    """Convert shared domain envelope kind enum into protobuf enum."""
    mapping = {
        EnvelopeKind.UNSPECIFIED: envelope_pb2.ENVELOPE_KIND_UNSPECIFIED,
        EnvelopeKind.COMMAND: envelope_pb2.ENVELOPE_KIND_COMMAND,
        EnvelopeKind.EVENT: envelope_pb2.ENVELOPE_KIND_EVENT,
        EnvelopeKind.RESULT: envelope_pb2.ENVELOPE_KIND_RESULT,
        EnvelopeKind.STREAM: envelope_pb2.ENVELOPE_KIND_STREAM,
    }
    return mapping[kind]


def _error_category_to_proto(category: ErrorCategory) -> envelope_pb2.ErrorCategory:
    """Convert shared domain error category enum into protobuf enum."""
    mapping = {
        ErrorCategory.UNSPECIFIED: envelope_pb2.ERROR_CATEGORY_UNSPECIFIED,
        ErrorCategory.VALIDATION: envelope_pb2.ERROR_CATEGORY_VALIDATION,
        ErrorCategory.CONFLICT: envelope_pb2.ERROR_CATEGORY_CONFLICT,
        ErrorCategory.NOT_FOUND: envelope_pb2.ERROR_CATEGORY_NOT_FOUND,
        ErrorCategory.POLICY: envelope_pb2.ERROR_CATEGORY_POLICY,
        ErrorCategory.DEPENDENCY: envelope_pb2.ERROR_CATEGORY_DEPENDENCY,
        ErrorCategory.INTERNAL: envelope_pb2.ERROR_CATEGORY_INTERNAL,
    }
    return mapping.get(category, envelope_pb2.ERROR_CATEGORY_UNSPECIFIED)


def _abort_for_transport_errors(
    *,
    context: grpc.ServicerContext,
    result: Result[object],
) -> None:
    """Abort gRPC request for transport/infrastructure failures only.

    Domain errors remain in the typed envelope error list. Infrastructure
    failures are surfaced as gRPC status failures.
    """
    for error in result.errors:
        if error.category == ErrorCategory.DEPENDENCY:
            context.abort(grpc.StatusCode.UNAVAILABLE, _transport_detail(error))
        elif error.category == ErrorCategory.INTERNAL:
            context.abort(grpc.StatusCode.INTERNAL, _transport_detail(error))


def _transport_detail(error: ErrorDetail) -> str:
    """Return deterministic error detail formatting for gRPC aborts."""
    return f"code={error.code}; message={error.message}"
