"""gRPC adapter entrypoints for Embedding Authority Service (EAS)."""

from __future__ import annotations

from datetime import datetime, timezone

import grpc
from brain.shared.v1 import envelope_pb2
from brain.state.v1 import embedding_pb2, embedding_pb2_grpc
from packages.brain_shared.envelope import EnvelopeKind, EnvelopeMeta, Result
from packages.brain_shared.errors import (
    ErrorCategory,
    ErrorDetail,
    codes,
    validation_error,
)
from services.state.embedding_authority.domain import (
    ChunkRecord,
    EmbeddingRecord,
    EmbeddingSpec,
    EmbeddingStatus,
    RepairSpecResult,
    SearchEmbeddingMatch,
    SourceRecord,
    UpsertChunkInput,
    UpsertChunkResult,
)
from services.state.embedding_authority.service import EmbeddingAuthorityService


class GrpcEmbeddingAuthorityService(
    embedding_pb2_grpc.EmbeddingAuthorityServiceServicer
):
    """gRPC servicer mapping transport requests into native EAS API calls."""

    def __init__(self, service: EmbeddingAuthorityService) -> None:
        self._service = service

    def UpsertSource(
        self, request: embedding_pb2.UpsertSourceRequest, context: grpc.ServicerContext
    ) -> embedding_pb2.UpsertSourceResponse:
        result = self._service.upsert_source(
            meta=_meta_from_proto(request.metadata),
            canonical_reference=request.payload.canonical_reference,
            source_type=request.payload.source_type,
            service=request.payload.service,
            principal=request.payload.principal,
            metadata=dict(request.payload.metadata),
        )
        _abort_for_transport_errors(context=context, result=result)
        return embedding_pb2.UpsertSourceResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=_source_to_proto(result.payload),
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def UpsertChunk(
        self, request: embedding_pb2.UpsertChunkRequest, context: grpc.ServicerContext
    ) -> embedding_pb2.UpsertChunkResponse:
        result = self._service.upsert_chunk(
            meta=_meta_from_proto(request.metadata),
            source_id=request.payload.source_id,
            chunk_ordinal=request.payload.chunk_ordinal,
            reference_range=request.payload.reference_range,
            content_hash=request.payload.content_hash,
            text=request.payload.text,
            metadata=dict(request.payload.metadata),
        )
        _abort_for_transport_errors(context=context, result=result)
        return embedding_pb2.UpsertChunkResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=_upsert_chunk_result_to_proto(result.payload),
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def UpsertChunks(
        self, request: embedding_pb2.UpsertChunksRequest, context: grpc.ServicerContext
    ) -> embedding_pb2.UpsertChunksResponse:
        items = [
            UpsertChunkInput(
                source_id=item.source_id,
                chunk_ordinal=item.chunk_ordinal,
                reference_range=item.reference_range,
                content_hash=item.content_hash,
                text=item.text,
                metadata=dict(item.metadata),
            )
            for item in request.payload.items
        ]
        result = self._service.upsert_chunks(
            meta=_meta_from_proto(request.metadata), items=items
        )
        _abort_for_transport_errors(context=context, result=result)
        payload = (
            []
            if result.payload is None
            else [_upsert_chunk_result_to_proto(item) for item in result.payload]
        )
        return embedding_pb2.UpsertChunksResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=payload,
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def DeleteChunk(
        self, request: embedding_pb2.DeleteChunkRequest, context: grpc.ServicerContext
    ) -> embedding_pb2.DeleteChunkResponse:
        result = self._service.delete_chunk(
            meta=_meta_from_proto(request.metadata),
            chunk_id=request.payload.chunk_id,
        )
        _abort_for_transport_errors(context=context, result=result)
        return embedding_pb2.DeleteChunkResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=bool(result.payload),
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def DeleteSource(
        self, request: embedding_pb2.DeleteSourceRequest, context: grpc.ServicerContext
    ) -> embedding_pb2.DeleteSourceResponse:
        result = self._service.delete_source(
            meta=_meta_from_proto(request.metadata),
            source_id=request.payload.source_id,
        )
        _abort_for_transport_errors(context=context, result=result)
        return embedding_pb2.DeleteSourceResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=bool(result.payload),
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def GetSource(
        self, request: embedding_pb2.GetSourceRequest, context: grpc.ServicerContext
    ) -> embedding_pb2.GetSourceResponse:
        result = self._service.get_source(
            meta=_meta_from_proto(request.metadata),
            source_id=request.payload.source_id,
        )
        _abort_for_transport_errors(context=context, result=result)
        return embedding_pb2.GetSourceResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=_source_to_proto(result.payload),
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def ListSources(
        self, request: embedding_pb2.ListSourcesRequest, context: grpc.ServicerContext
    ) -> embedding_pb2.ListSourcesResponse:
        result = self._service.list_sources(
            meta=_meta_from_proto(request.metadata),
            canonical_reference=request.payload.canonical_reference,
            service=request.payload.service,
            principal=request.payload.principal,
            limit=request.payload.limit,
        )
        _abort_for_transport_errors(context=context, result=result)
        payload = (
            []
            if result.payload is None
            else [_source_to_proto(item) for item in result.payload]
        )
        return embedding_pb2.ListSourcesResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=payload,
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def GetChunk(
        self, request: embedding_pb2.GetChunkRequest, context: grpc.ServicerContext
    ) -> embedding_pb2.GetChunkResponse:
        result = self._service.get_chunk(
            meta=_meta_from_proto(request.metadata),
            chunk_id=request.payload.chunk_id,
        )
        _abort_for_transport_errors(context=context, result=result)
        return embedding_pb2.GetChunkResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=_chunk_to_proto(result.payload),
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def ListChunksBySource(
        self,
        request: embedding_pb2.ListChunksBySourceRequest,
        context: grpc.ServicerContext,
    ) -> embedding_pb2.ListChunksBySourceResponse:
        result = self._service.list_chunks_by_source(
            meta=_meta_from_proto(request.metadata),
            source_id=request.payload.source_id,
            limit=request.payload.limit,
        )
        _abort_for_transport_errors(context=context, result=result)
        payload = (
            []
            if result.payload is None
            else [_chunk_to_proto(item) for item in result.payload]
        )
        return embedding_pb2.ListChunksBySourceResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=payload,
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def GetEmbedding(
        self, request: embedding_pb2.GetEmbeddingRequest, context: grpc.ServicerContext
    ) -> embedding_pb2.GetEmbeddingResponse:
        result = self._service.get_embedding(
            meta=_meta_from_proto(request.metadata),
            chunk_id=request.payload.chunk_id,
            spec_id=request.payload.spec_id,
        )
        _abort_for_transport_errors(context=context, result=result)
        return embedding_pb2.GetEmbeddingResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=_embedding_to_proto(result.payload),
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def ListEmbeddingsBySource(
        self,
        request: embedding_pb2.ListEmbeddingsBySourceRequest,
        context: grpc.ServicerContext,
    ) -> embedding_pb2.ListEmbeddingsBySourceResponse:
        result = self._service.list_embeddings_by_source(
            meta=_meta_from_proto(request.metadata),
            source_id=request.payload.source_id,
            spec_id=request.payload.spec_id,
            limit=request.payload.limit,
        )
        _abort_for_transport_errors(context=context, result=result)
        payload = (
            []
            if result.payload is None
            else [_embedding_to_proto(item) for item in result.payload]
        )
        return embedding_pb2.ListEmbeddingsBySourceResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=payload,
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def ListEmbeddingsByStatus(
        self,
        request: embedding_pb2.ListEmbeddingsByStatusRequest,
        context: grpc.ServicerContext,
    ) -> embedding_pb2.ListEmbeddingsByStatusResponse:
        mapped_status = _status_from_proto(request.payload.status)
        if mapped_status is None:
            meta = _meta_from_proto(request.metadata)
            return embedding_pb2.ListEmbeddingsByStatusResponse(
                metadata=_meta_to_proto(meta),
                payload=[],
                errors=[
                    _error_to_proto(
                        validation_error(
                            "status must be specified",
                            code=codes.INVALID_ARGUMENT,
                        )
                    )
                ],
            )
        result = self._service.list_embeddings_by_status(
            meta=_meta_from_proto(request.metadata),
            status=mapped_status,
            spec_id=request.payload.spec_id,
            limit=request.payload.limit,
        )
        _abort_for_transport_errors(context=context, result=result)
        payload = (
            []
            if result.payload is None
            else [_embedding_to_proto(item) for item in result.payload]
        )
        return embedding_pb2.ListEmbeddingsByStatusResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=payload,
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def SearchEmbeddings(
        self,
        request: embedding_pb2.SearchEmbeddingsRequest,
        context: grpc.ServicerContext,
    ) -> embedding_pb2.SearchEmbeddingsResponse:
        result = self._service.search_embeddings(
            meta=_meta_from_proto(request.metadata),
            query_text=request.payload.query_text,
            source_id=request.payload.source_id,
            spec_id=request.payload.spec_id,
            limit=request.payload.limit,
        )
        _abort_for_transport_errors(context=context, result=result)
        payload = (
            []
            if result.payload is None
            else [_search_match_to_proto(item) for item in result.payload]
        )
        return embedding_pb2.SearchEmbeddingsResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=payload,
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def GetActiveSpec(
        self, request: embedding_pb2.GetActiveSpecRequest, context: grpc.ServicerContext
    ) -> embedding_pb2.GetActiveSpecResponse:
        result = self._service.get_active_spec(meta=_meta_from_proto(request.metadata))
        _abort_for_transport_errors(context=context, result=result)
        return embedding_pb2.GetActiveSpecResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=_spec_to_proto(result.payload),
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def ListSpecs(
        self, request: embedding_pb2.ListSpecsRequest, context: grpc.ServicerContext
    ) -> embedding_pb2.ListSpecsResponse:
        result = self._service.list_specs(
            meta=_meta_from_proto(request.metadata), limit=request.payload.limit
        )
        _abort_for_transport_errors(context=context, result=result)
        payload = (
            []
            if result.payload is None
            else [_spec_to_proto(item) for item in result.payload]
        )
        return embedding_pb2.ListSpecsResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=payload,
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def GetSpec(
        self, request: embedding_pb2.GetSpecRequest, context: grpc.ServicerContext
    ) -> embedding_pb2.GetSpecResponse:
        result = self._service.get_spec(
            meta=_meta_from_proto(request.metadata), spec_id=request.payload.spec_id
        )
        _abort_for_transport_errors(context=context, result=result)
        return embedding_pb2.GetSpecResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=_spec_to_proto(result.payload),
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def RepairSpec(
        self, request: embedding_pb2.RepairSpecRequest, context: grpc.ServicerContext
    ) -> embedding_pb2.RepairSpecResponse:
        result = self._service.repair_spec(
            meta=_meta_from_proto(request.metadata),
            spec_id=request.payload.spec_id,
            limit=request.payload.limit,
        )
        _abort_for_transport_errors(context=context, result=result)
        return embedding_pb2.RepairSpecResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=_repair_to_proto(result.payload),
            errors=[_error_to_proto(item) for item in result.errors],
        )


def register_embedding_authority_service(
    server: grpc.Server, service: EmbeddingAuthorityService
) -> None:
    """Attach the EAS gRPC servicer to a server."""
    embedding_pb2_grpc.add_EmbeddingAuthorityServiceServicer_to_server(
        GrpcEmbeddingAuthorityService(service=service),
        server,
    )


def _meta_from_proto(meta: envelope_pb2.EnvelopeMeta) -> EnvelopeMeta:
    """Map protobuf metadata to shared native envelope metadata."""
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
    """Map shared native envelope metadata to protobuf metadata."""
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
    """Map shared typed errors to protobuf errors."""
    return envelope_pb2.ErrorDetail(
        code=error.code,
        message=error.message,
        category=_error_category_to_proto(error.category),
        retryable=error.retryable,
        metadata=dict(error.metadata),
    )


def _source_to_proto(source: SourceRecord | None) -> embedding_pb2.SourceRecord:
    """Map source row to protobuf payload."""
    if source is None:
        return embedding_pb2.SourceRecord()
    message = embedding_pb2.SourceRecord(
        id=source.id,
        source_type=source.source_type,
        canonical_reference=source.canonical_reference,
        service=source.service,
        principal=source.principal,
        metadata=dict(source.metadata),
    )
    message.created_at.FromDatetime(_utc(source.created_at))
    message.updated_at.FromDatetime(_utc(source.updated_at))
    return message


def _chunk_to_proto(chunk: ChunkRecord | None) -> embedding_pb2.ChunkRecord:
    """Map chunk row to protobuf payload."""
    if chunk is None:
        return embedding_pb2.ChunkRecord()
    message = embedding_pb2.ChunkRecord(
        id=chunk.id,
        source_id=chunk.source_id,
        chunk_ordinal=chunk.chunk_ordinal,
        reference_range=chunk.reference_range,
        content_hash=chunk.content_hash,
        metadata=dict(chunk.metadata),
        text=chunk.text,
    )
    message.created_at.FromDatetime(_utc(chunk.created_at))
    message.updated_at.FromDatetime(_utc(chunk.updated_at))
    return message


def _embedding_to_proto(
    embedding: EmbeddingRecord | None,
) -> embedding_pb2.EmbeddingRecord:
    """Map embedding row to protobuf payload."""
    if embedding is None:
        return embedding_pb2.EmbeddingRecord()
    message = embedding_pb2.EmbeddingRecord(
        chunk_id=embedding.chunk_id,
        spec_id=embedding.spec_id,
        content_hash=embedding.content_hash,
        status=_status_to_proto(embedding.status),
        error_detail=embedding.error_detail,
    )
    message.created_at.FromDatetime(_utc(embedding.created_at))
    message.updated_at.FromDatetime(_utc(embedding.updated_at))
    return message


def _spec_to_proto(spec: EmbeddingSpec | None) -> embedding_pb2.EmbeddingSpec:
    """Map embedding spec row to protobuf payload."""
    if spec is None:
        return embedding_pb2.EmbeddingSpec()
    message = embedding_pb2.EmbeddingSpec(
        id=spec.id,
        provider=spec.provider,
        name=spec.name,
        version=spec.version,
        dimensions=spec.dimensions,
        hash=spec.hash,
        canonical_string=spec.canonical_string,
    )
    message.created_at.FromDatetime(_utc(spec.created_at))
    message.updated_at.FromDatetime(_utc(spec.updated_at))
    return message


def _repair_to_proto(repair: RepairSpecResult | None) -> embedding_pb2.RepairSpecResult:
    """Map repair summary to protobuf payload."""
    if repair is None:
        return embedding_pb2.RepairSpecResult()
    return embedding_pb2.RepairSpecResult(
        spec_id=repair.spec_id,
        scanned=repair.scanned,
        repaired=repair.repaired,
        reembedded=repair.reembedded,
    )


def _search_match_to_proto(
    match: SearchEmbeddingMatch | None,
) -> embedding_pb2.SearchEmbeddingMatch:
    """Map semantic search match payload to protobuf payload."""
    if match is None:
        return embedding_pb2.SearchEmbeddingMatch()
    return embedding_pb2.SearchEmbeddingMatch(
        score=match.score,
        chunk_id=match.chunk_id,
        source_id=match.source_id,
        spec_id=match.spec_id,
        chunk_ordinal=match.chunk_ordinal,
        reference_range=match.reference_range,
        content_hash=match.content_hash,
    )


def _upsert_chunk_result_to_proto(
    value: UpsertChunkResult | None,
) -> embedding_pb2.UpsertChunkResult:
    """Map upsert result payload to protobuf payload."""
    if value is None:
        return embedding_pb2.UpsertChunkResult()
    return embedding_pb2.UpsertChunkResult(
        chunk=_chunk_to_proto(value.chunk),
        embedding=_embedding_to_proto(value.embedding),
    )


def _kind_from_proto(kind: envelope_pb2.EnvelopeKind) -> EnvelopeKind:
    """Map protobuf envelope kind to shared kind enum."""
    mapping = {
        envelope_pb2.ENVELOPE_KIND_UNSPECIFIED: EnvelopeKind.UNSPECIFIED,
        envelope_pb2.ENVELOPE_KIND_COMMAND: EnvelopeKind.COMMAND,
        envelope_pb2.ENVELOPE_KIND_EVENT: EnvelopeKind.EVENT,
        envelope_pb2.ENVELOPE_KIND_RESULT: EnvelopeKind.RESULT,
        envelope_pb2.ENVELOPE_KIND_STREAM: EnvelopeKind.STREAM,
    }
    return mapping.get(kind, EnvelopeKind.UNSPECIFIED)


def _kind_to_proto(kind: EnvelopeKind) -> envelope_pb2.EnvelopeKind:
    """Map shared envelope kind enum to protobuf kind."""
    mapping = {
        EnvelopeKind.UNSPECIFIED: envelope_pb2.ENVELOPE_KIND_UNSPECIFIED,
        EnvelopeKind.COMMAND: envelope_pb2.ENVELOPE_KIND_COMMAND,
        EnvelopeKind.EVENT: envelope_pb2.ENVELOPE_KIND_EVENT,
        EnvelopeKind.RESULT: envelope_pb2.ENVELOPE_KIND_RESULT,
        EnvelopeKind.STREAM: envelope_pb2.ENVELOPE_KIND_STREAM,
    }
    return mapping[kind]


def _status_from_proto(status: embedding_pb2.EmbeddingStatus) -> EmbeddingStatus | None:
    """Map protobuf status enum to domain status enum."""
    mapping = {
        embedding_pb2.EMBEDDING_STATUS_PENDING: EmbeddingStatus.PENDING,
        embedding_pb2.EMBEDDING_STATUS_INDEXED: EmbeddingStatus.INDEXED,
        embedding_pb2.EMBEDDING_STATUS_FAILED: EmbeddingStatus.FAILED,
    }
    return mapping.get(status)


def _status_to_proto(status: EmbeddingStatus) -> embedding_pb2.EmbeddingStatus:
    """Map domain status enum to protobuf status enum."""
    mapping = {
        EmbeddingStatus.PENDING: embedding_pb2.EMBEDDING_STATUS_PENDING,
        EmbeddingStatus.INDEXED: embedding_pb2.EMBEDDING_STATUS_INDEXED,
        EmbeddingStatus.FAILED: embedding_pb2.EMBEDDING_STATUS_FAILED,
    }
    return mapping[status]


def _error_category_to_proto(category: ErrorCategory) -> envelope_pb2.ErrorCategory:
    """Map shared error categories to protobuf categories."""
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
    *, context: grpc.ServicerContext, result: Result[object]
) -> None:
    """Map infrastructure failures to transport failures only."""
    for error in result.errors:
        if error.category == ErrorCategory.DEPENDENCY:
            context.abort(grpc.StatusCode.UNAVAILABLE, _transport_detail(error))
        if error.category == ErrorCategory.INTERNAL:
            context.abort(grpc.StatusCode.INTERNAL, _transport_detail(error))


def _transport_detail(error: ErrorDetail) -> str:
    """Build deterministic transport error detail string."""
    return f"code={error.code}; message={error.message}"


def _utc(value: datetime) -> datetime:
    """Normalize datetimes for protobuf timestamp conversion."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
