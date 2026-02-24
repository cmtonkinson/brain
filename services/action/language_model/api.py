"""gRPC adapter entrypoints for Language Model Service."""

from __future__ import annotations

from datetime import datetime, timezone

import grpc
from brain.action.v1 import language_model_pb2, language_model_pb2_grpc
from brain.shared.v1 import envelope_pb2
from packages.brain_shared.envelope import Envelope, EnvelopeKind, EnvelopeMeta
from packages.brain_shared.errors import (
    ErrorCategory,
    ErrorDetail,
    codes,
    validation_error,
)
from services.action.language_model.domain import (
    ChatResponse,
    EmbeddingVector,
    HealthStatus,
)
from services.action.language_model.service import LanguageModelService
from services.action.language_model.validation import EmbeddingProfile, ReasoningLevel


class GrpcLanguageModelService(language_model_pb2_grpc.LanguageModelServiceServicer):
    """gRPC servicer mapping transport requests into native LMS API calls."""

    def __init__(self, service: LanguageModelService) -> None:
        self._service = service

    def Chat(
        self, request: language_model_pb2.ChatRequest, context: grpc.ServicerContext
    ) -> language_model_pb2.ChatResponse:
        profile = _reasoning_level_from_proto(request.payload.profile)
        if profile is None:
            meta = _meta_from_proto(request.metadata)
            return language_model_pb2.ChatResponse(
                metadata=_meta_to_proto(meta),
                payload=language_model_pb2.ChatResult(),
                errors=[
                    _error_to_proto(
                        validation_error(
                            "profile must be quick, standard, or deep",
                            code=codes.INVALID_ARGUMENT,
                        )
                    )
                ],
            )

        result = self._service.chat(
            meta=_meta_from_proto(request.metadata),
            prompt=request.payload.prompt,
            profile=profile,
        )
        _abort_for_transport_errors(context=context, result=result)
        return language_model_pb2.ChatResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=_chat_to_proto(
                None if result.payload is None else result.payload.value
            ),
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def ChatBatch(
        self,
        request: language_model_pb2.ChatBatchRequest,
        context: grpc.ServicerContext,
    ) -> language_model_pb2.ChatBatchResponse:
        profile = _reasoning_level_from_proto(request.payload.profile)
        if profile is None:
            meta = _meta_from_proto(request.metadata)
            return language_model_pb2.ChatBatchResponse(
                metadata=_meta_to_proto(meta),
                payload=[],
                errors=[
                    _error_to_proto(
                        validation_error(
                            "profile must be quick, standard, or deep",
                            code=codes.INVALID_ARGUMENT,
                        )
                    )
                ],
            )

        result = self._service.chat_batch(
            meta=_meta_from_proto(request.metadata),
            prompts=list(request.payload.prompts),
            profile=profile,
        )
        _abort_for_transport_errors(context=context, result=result)
        payload = (
            []
            if result.payload is None
            else [_chat_to_proto(item) for item in result.payload.value]
        )
        return language_model_pb2.ChatBatchResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=payload,
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def Embed(
        self, request: language_model_pb2.EmbedRequest, context: grpc.ServicerContext
    ) -> language_model_pb2.EmbedResponse:
        profile = _embed_profile_from_proto(request.payload.profile)
        if profile is None:
            meta = _meta_from_proto(request.metadata)
            return language_model_pb2.EmbedResponse(
                metadata=_meta_to_proto(meta),
                payload=language_model_pb2.EmbeddingVector(),
                errors=[
                    _error_to_proto(
                        validation_error(
                            "profile must be embedding",
                            code=codes.INVALID_ARGUMENT,
                        )
                    )
                ],
            )

        result = self._service.embed(
            meta=_meta_from_proto(request.metadata),
            text=request.payload.text,
            profile=profile,
        )
        _abort_for_transport_errors(context=context, result=result)
        return language_model_pb2.EmbedResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=_embedding_to_proto(
                None if result.payload is None else result.payload.value
            ),
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def EmbedBatch(
        self,
        request: language_model_pb2.EmbedBatchRequest,
        context: grpc.ServicerContext,
    ) -> language_model_pb2.EmbedBatchResponse:
        profile = _embed_profile_from_proto(request.payload.profile)
        if profile is None:
            meta = _meta_from_proto(request.metadata)
            return language_model_pb2.EmbedBatchResponse(
                metadata=_meta_to_proto(meta),
                payload=[],
                errors=[
                    _error_to_proto(
                        validation_error(
                            "profile must be embedding",
                            code=codes.INVALID_ARGUMENT,
                        )
                    )
                ],
            )

        result = self._service.embed_batch(
            meta=_meta_from_proto(request.metadata),
            texts=list(request.payload.texts),
            profile=profile,
        )
        _abort_for_transport_errors(context=context, result=result)
        payload = (
            []
            if result.payload is None
            else [_embedding_to_proto(item) for item in result.payload.value]
        )
        return language_model_pb2.EmbedBatchResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=payload,
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def Health(
        self, request: language_model_pb2.HealthRequest, context: grpc.ServicerContext
    ) -> language_model_pb2.HealthResponse:
        result = self._service.health(meta=_meta_from_proto(request.metadata))
        _abort_for_transport_errors(context=context, result=result)
        return language_model_pb2.HealthResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=_health_to_proto(
                None if result.payload is None else result.payload.value
            ),
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
    if len(dependency_messages) > 0:
        context.abort(grpc.StatusCode.UNAVAILABLE, "; ".join(dependency_messages))

    internal_messages = [
        error.message
        for error in result.errors
        if error.category == ErrorCategory.INTERNAL
    ]
    if len(internal_messages) > 0:
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


def _reasoning_level_from_proto(profile: int) -> ReasoningLevel | None:
    """Map protobuf enum into chat reasoning level selector."""
    if profile == language_model_pb2.REASONING_LEVEL_QUICK:
        return ReasoningLevel.QUICK
    if profile in (
        language_model_pb2.REASONING_LEVEL_STANDARD,
        language_model_pb2.REASONING_LEVEL_UNSPECIFIED,
    ):
        return ReasoningLevel.STANDARD
    if profile == language_model_pb2.REASONING_LEVEL_DEEP:
        return ReasoningLevel.DEEP
    return None


def _embed_profile_from_proto(profile: int) -> EmbeddingProfile | None:
    """Map protobuf profile enum into embed-capable profile selector."""
    if profile in (
        language_model_pb2.EMBEDDING_PROFILE_EMBEDDING,
        language_model_pb2.EMBEDDING_PROFILE_UNSPECIFIED,
    ):
        return EmbeddingProfile.EMBEDDING
    return None


def _chat_to_proto(payload: ChatResponse | None) -> language_model_pb2.ChatResult:
    """Convert chat domain payload into protobuf shape."""
    if payload is None:
        return language_model_pb2.ChatResult()
    return language_model_pb2.ChatResult(
        text=payload.text,
        provider=payload.provider,
        model=payload.model,
    )


def _embedding_to_proto(
    payload: EmbeddingVector | None,
) -> language_model_pb2.EmbeddingVector:
    """Convert embedding domain payload into protobuf shape."""
    if payload is None:
        return language_model_pb2.EmbeddingVector()
    return language_model_pb2.EmbeddingVector(
        values=list(payload.values),
        provider=payload.provider,
        model=payload.model,
    )


def _health_to_proto(payload: HealthStatus | None) -> language_model_pb2.HealthStatus:
    """Convert health domain payload into protobuf shape."""
    if payload is None:
        return language_model_pb2.HealthStatus()
    return language_model_pb2.HealthStatus(
        service_ready=payload.service_ready,
        adapter_ready=payload.adapter_ready,
        detail=payload.detail,
    )


def _error_to_proto(error: ErrorDetail) -> envelope_pb2.ErrorDetail:
    """Convert one canonical shared error detail into protobuf shape."""
    return envelope_pb2.ErrorDetail(
        code=error.code,
        message=error.message,
        category=_category_to_proto(error.category),
        retryable=error.retryable,
        metadata=dict(error.metadata),
    )


def _category_to_proto(category: ErrorCategory) -> int:
    """Map shared error category enum into protobuf enum value."""
    if category == ErrorCategory.VALIDATION:
        return envelope_pb2.ERROR_CATEGORY_VALIDATION
    if category == ErrorCategory.CONFLICT:
        return envelope_pb2.ERROR_CATEGORY_CONFLICT
    if category == ErrorCategory.NOT_FOUND:
        return envelope_pb2.ERROR_CATEGORY_NOT_FOUND
    if category == ErrorCategory.POLICY:
        return envelope_pb2.ERROR_CATEGORY_POLICY
    if category == ErrorCategory.DEPENDENCY:
        return envelope_pb2.ERROR_CATEGORY_DEPENDENCY
    if category == ErrorCategory.INTERNAL:
        return envelope_pb2.ERROR_CATEGORY_INTERNAL
    return envelope_pb2.ERROR_CATEGORY_UNSPECIFIED
