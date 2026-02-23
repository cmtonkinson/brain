"""Adapter tests for LMS gRPC transport/domain error mapping semantics."""
# ruff: noqa: E402

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import grpc
import pytest


def _repo_root() -> Path:
    """Resolve repository root by walking up to the directory containing Makefile."""
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "Makefile").exists():
            return candidate
    raise RuntimeError("repository root not found from test path")


repo_root = _repo_root()
generated_root = repo_root / "generated"
if not generated_root.exists():
    pytest.skip(
        "generated protobuf stubs not present; run `make build` before this test",
        allow_module_level=True,
    )
sys.path.insert(0, str(generated_root))

from packages.brain_shared.envelope import (  # noqa: E402
    EnvelopeKind,
    EnvelopeMeta,
    failure,
    new_meta,
    success,
)
from packages.brain_shared.envelope.envelope import Envelope  # noqa: E402
from packages.brain_shared.errors import (  # noqa: E402
    ErrorCategory,
    codes,
    dependency_error,
    internal_error,
    validation_error,
)
from services.action.language_model.api import (  # noqa: E402
    GrpcLanguageModelService,
    _abort_for_transport_errors,
    _chat_profile_from_proto,
    _embed_profile_from_proto,
    _meta_to_proto,
)
from services.action.language_model.domain import (  # noqa: E402
    ChatResponse,
    EmbeddingVector,
    HealthStatus,
)
from services.action.language_model.validation import ModelProfile  # noqa: E402
from brain.action.v1 import language_model_pb2  # noqa: E402


@dataclass(frozen=True)
class _Call:
    """One fake LMS call captured by method/profile."""

    method: str
    profile: ModelProfile | None


class _AbortCalled(RuntimeError):
    """Raised by fake gRPC context when abort() is invoked."""


class _FakeServicerContext:
    """Minimal gRPC context stub for testing transport abort mapping."""

    def __init__(self) -> None:
        self.code: grpc.StatusCode | None = None
        self.details: str | None = None

    def abort(self, code: grpc.StatusCode, details: str) -> None:
        self.code = code
        self.details = details
        raise _AbortCalled(details)


class _FakeLanguageModelService:
    """Service fake with programmable envelopes for gRPC adapter testing."""

    def __init__(self) -> None:
        self.calls: list[_Call] = []
        self.chat_result = success(
            meta=_meta(),
            payload=ChatResponse(text="chat-ok", provider="ollama", model="gpt-oss"),
        )
        self.chat_batch_result = success(
            meta=_meta(),
            payload=[
                ChatResponse(text="a", provider="ollama", model="gpt-oss"),
                ChatResponse(text="b", provider="ollama", model="gpt-oss"),
            ],
        )
        self.embed_result = success(
            meta=_meta(),
            payload=EmbeddingVector(
                values=(0.1, 0.2), provider="ollama", model="embed"
            ),
        )
        self.embed_batch_result = success(
            meta=_meta(),
            payload=[
                EmbeddingVector(values=(0.1, 0.2), provider="ollama", model="embed"),
                EmbeddingVector(values=(0.3, 0.4), provider="ollama", model="embed"),
            ],
        )
        self.health_result = success(
            meta=_meta(),
            payload=HealthStatus(
                service_ready=True,
                adapter_ready=True,
                detail="ok",
            ),
        )

    def chat(
        self,
        *,
        meta: EnvelopeMeta,
        prompt: str,
        profile: ModelProfile = ModelProfile.CHAT_DEFAULT,
    ) -> Envelope[ChatResponse]:
        del meta, prompt
        self.calls.append(_Call(method="chat", profile=profile))
        return self.chat_result

    def chat_batch(
        self,
        *,
        meta: EnvelopeMeta,
        prompts: Sequence[str],
        profile: ModelProfile = ModelProfile.CHAT_DEFAULT,
    ) -> Envelope[list[ChatResponse]]:
        del meta, prompts
        self.calls.append(_Call(method="chat_batch", profile=profile))
        return self.chat_batch_result

    def embed(
        self,
        *,
        meta: EnvelopeMeta,
        text: str,
        profile: ModelProfile = ModelProfile.EMBEDDING,
    ) -> Envelope[EmbeddingVector]:
        del meta, text
        self.calls.append(_Call(method="embed", profile=profile))
        return self.embed_result

    def embed_batch(
        self,
        *,
        meta: EnvelopeMeta,
        texts: Sequence[str],
        profile: ModelProfile = ModelProfile.EMBEDDING,
    ) -> Envelope[list[EmbeddingVector]]:
        del meta, texts
        self.calls.append(_Call(method="embed_batch", profile=profile))
        return self.embed_batch_result

    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        del meta
        self.calls.append(_Call(method="health", profile=None))
        return self.health_result


def _meta() -> EnvelopeMeta:
    """Build valid envelope metadata for transport tests."""
    return new_meta(kind=EnvelopeKind.COMMAND, source="grpc-test", principal="operator")


def _envelope_with_error(*, category: ErrorCategory) -> Envelope[object]:
    """Construct one failed envelope with selected error category."""
    if category == ErrorCategory.DEPENDENCY:
        error = dependency_error(
            "dependency unavailable", code=codes.DEPENDENCY_UNAVAILABLE
        )
    elif category == ErrorCategory.INTERNAL:
        error = internal_error("internal failure", code=codes.INTERNAL_ERROR)
    else:
        error = validation_error("invalid", code=codes.INVALID_ARGUMENT)
    return failure(meta=_meta(), errors=[error])


def test_abort_maps_dependency_errors_to_unavailable() -> None:
    """Dependency-category errors must map to gRPC UNAVAILABLE transport failures."""
    context = _FakeServicerContext()
    envelope = _envelope_with_error(category=ErrorCategory.DEPENDENCY)

    with pytest.raises(_AbortCalled):
        _abort_for_transport_errors(context=context, result=envelope)

    assert context.code == grpc.StatusCode.UNAVAILABLE
    assert context.details is not None
    assert "dependency unavailable" in context.details


def test_abort_maps_internal_errors_to_internal() -> None:
    """Internal-category errors must map to gRPC INTERNAL transport failures."""
    context = _FakeServicerContext()
    envelope = _envelope_with_error(category=ErrorCategory.INTERNAL)

    with pytest.raises(_AbortCalled):
        _abort_for_transport_errors(context=context, result=envelope)

    assert context.code == grpc.StatusCode.INTERNAL
    assert context.details is not None
    assert "internal failure" in context.details


def test_abort_ignores_domain_errors() -> None:
    """Domain errors should stay in envelope errors and not abort transport."""
    context = _FakeServicerContext()
    envelope = _envelope_with_error(category=ErrorCategory.VALIDATION)

    _abort_for_transport_errors(context=context, result=envelope)

    assert context.code is None
    assert context.details is None


def test_chat_profile_mapping_rejects_embedding_profile() -> None:
    """Chat mapping should reject embedding profile at gRPC ingress."""
    mapped = _chat_profile_from_proto(language_model_pb2.MODEL_PROFILE_EMBEDDING)
    assert mapped is None


def test_embed_profile_mapping_rejects_chat_profile() -> None:
    """Embed mapping should reject chat profiles at gRPC ingress."""
    mapped = _embed_profile_from_proto(language_model_pb2.MODEL_PROFILE_CHAT_DEFAULT)
    assert mapped is None


def test_profile_mapping_defaults_unspecified() -> None:
    """Unspecified profile should default to method-appropriate profile."""
    mapped_chat = _chat_profile_from_proto(language_model_pb2.MODEL_PROFILE_UNSPECIFIED)
    mapped_embed = _embed_profile_from_proto(
        language_model_pb2.MODEL_PROFILE_UNSPECIFIED
    )
    assert mapped_chat == ModelProfile.CHAT_DEFAULT
    assert mapped_embed == ModelProfile.EMBEDDING


def test_chat_routes_to_service_and_maps_payload() -> None:
    """Chat should route with mapped profile and return protobuf payload fields."""
    service = _FakeLanguageModelService()
    grpc_service = GrpcLanguageModelService(service=service)
    context = _FakeServicerContext()

    response = grpc_service.Chat(
        language_model_pb2.ChatRequest(
            metadata=_meta_to_proto(_meta()),
            payload=language_model_pb2.ChatPayload(
                prompt="hello",
                profile=language_model_pb2.MODEL_PROFILE_CHAT_ADVANCED,
            ),
        ),
        context,
    )

    assert service.calls[-1] == _Call(method="chat", profile=ModelProfile.CHAT_ADVANCED)
    assert response.payload.text == "chat-ok"
    assert response.payload.provider == "ollama"
    assert response.payload.model == "gpt-oss"
    assert response.errors == []


def test_chat_returns_validation_error_without_service_call_for_invalid_profile() -> (
    None
):
    """Chat ingress should reject invalid profile enums before service invocation."""
    service = _FakeLanguageModelService()
    grpc_service = GrpcLanguageModelService(service=service)
    context = _FakeServicerContext()

    response = grpc_service.Chat(
        language_model_pb2.ChatRequest(
            metadata=_meta_to_proto(_meta()),
            payload=language_model_pb2.ChatPayload(
                prompt="hello",
                profile=language_model_pb2.MODEL_PROFILE_EMBEDDING,
            ),
        ),
        context,
    )

    assert service.calls == []
    assert len(response.errors) == 1
    assert response.errors[0].code == codes.INVALID_ARGUMENT
    assert response.errors[0].message == "profile must be chat_default or chat_advanced"


def test_embed_batch_routes_to_service_and_maps_payload() -> None:
    """Embed batch should map vectors and preserve ordering from service payload."""
    service = _FakeLanguageModelService()
    grpc_service = GrpcLanguageModelService(service=service)
    context = _FakeServicerContext()

    response = grpc_service.EmbedBatch(
        language_model_pb2.EmbedBatchRequest(
            metadata=_meta_to_proto(_meta()),
            payload=language_model_pb2.EmbedBatchPayload(
                texts=["a", "b"],
                profile=language_model_pb2.MODEL_PROFILE_EMBEDDING,
            ),
        ),
        context,
    )

    assert service.calls[-1] == _Call(
        method="embed_batch", profile=ModelProfile.EMBEDDING
    )
    assert len(response.payload) == 2
    assert list(response.payload[0].values) == pytest.approx([0.1, 0.2])
    assert list(response.payload[1].values) == pytest.approx([0.3, 0.4])


def test_embed_batch_returns_validation_error_for_invalid_profile() -> None:
    """Embed batch ingress should reject chat profile enums with validation error."""
    service = _FakeLanguageModelService()
    grpc_service = GrpcLanguageModelService(service=service)
    context = _FakeServicerContext()

    response = grpc_service.EmbedBatch(
        language_model_pb2.EmbedBatchRequest(
            metadata=_meta_to_proto(_meta()),
            payload=language_model_pb2.EmbedBatchPayload(
                texts=["a"],
                profile=language_model_pb2.MODEL_PROFILE_CHAT_DEFAULT,
            ),
        ),
        context,
    )

    assert service.calls == []
    assert len(response.errors) == 1
    assert response.errors[0].message == "profile must be embedding"


def test_chat_aborts_transport_on_dependency_error() -> None:
    """Chat should abort with UNAVAILABLE when service envelope has dependency errors."""
    service = _FakeLanguageModelService()
    service.chat_result = _envelope_with_error(category=ErrorCategory.DEPENDENCY)
    grpc_service = GrpcLanguageModelService(service=service)
    context = _FakeServicerContext()

    with pytest.raises(_AbortCalled):
        grpc_service.Chat(
            language_model_pb2.ChatRequest(
                metadata=_meta_to_proto(_meta()),
                payload=language_model_pb2.ChatPayload(prompt="hello"),
            ),
            context,
        )

    assert context.code == grpc.StatusCode.UNAVAILABLE


def test_health_aborts_transport_on_internal_error() -> None:
    """Health should abort with INTERNAL when service reports internal errors."""
    service = _FakeLanguageModelService()
    service.health_result = _envelope_with_error(category=ErrorCategory.INTERNAL)
    grpc_service = GrpcLanguageModelService(service=service)
    context = _FakeServicerContext()

    with pytest.raises(_AbortCalled):
        grpc_service.Health(
            language_model_pb2.HealthRequest(metadata=_meta_to_proto(_meta())),
            context,
        )

    assert context.code == grpc.StatusCode.INTERNAL


def test_health_routes_payload_without_errors() -> None:
    """Health should map successful service readiness payload into protobuf response."""
    service = _FakeLanguageModelService()
    service.health_result = success(
        meta=_meta(),
        payload=HealthStatus(
            service_ready=True, adapter_ready=False, detail="degraded"
        ),
    )
    grpc_service = GrpcLanguageModelService(service=service)
    context = _FakeServicerContext()

    response = grpc_service.Health(
        language_model_pb2.HealthRequest(metadata=_meta_to_proto(_meta())),
        context,
    )

    assert service.calls[-1] == _Call(method="health", profile=None)
    assert response.payload.service_ready is True
    assert response.payload.adapter_ready is False
    assert response.payload.detail == "degraded"
    assert response.errors == []


def test_error_category_maps_to_proto_enum_for_validation() -> None:
    """Validation envelope errors should retain category in protobuf mapping."""
    service = _FakeLanguageModelService()
    service.embed_result = failure(
        meta=_meta(),
        errors=[validation_error("text required", code=codes.INVALID_ARGUMENT)],
    )
    grpc_service = GrpcLanguageModelService(service=service)
    context = _FakeServicerContext()

    response = grpc_service.Embed(
        language_model_pb2.EmbedRequest(
            metadata=_meta_to_proto(_meta()),
            payload=language_model_pb2.EmbedPayload(
                text="",
                profile=language_model_pb2.MODEL_PROFILE_EMBEDDING,
            ),
        ),
        context,
    )

    assert len(response.errors) == 1
    assert response.errors[0].category == 1  # ERROR_CATEGORY_VALIDATION
    assert response.errors[0].message == "text required"
    assert context.code is None
