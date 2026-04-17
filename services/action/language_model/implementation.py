"""Concrete Language Model Service implementation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Sequence

from pydantic import BaseModel, ValidationError

from packages.brain_shared.config import CoreRuntimeSettings
from packages.brain_shared.envelope import (
    Envelope,
    EnvelopeMeta,
    failure,
    success,
    validate_meta,
)
from packages.brain_shared.errors import (
    ErrorDetail,
    codes,
    dependency_error,
    internal_error,
    validation_error,
)
from packages.brain_shared.logging import get_logger, public_api_instrumented
from resources.adapters.llm import (
    AdapterDependencyError,
    AdapterInternalError,
    AdapterProviderCallAudit,
    LlmAdapter,
    HttpLlmAdapter,
    resolve_llm_adapter_settings,
)
from services.action.language_model.component import SERVICE_COMPONENT_ID
from services.action.language_model.config import (
    LanguageModelEmbeddingProfileSettings,
    LanguageModelProfileSettings,
    LanguageModelServiceSettings,
    resolve_language_model_service_settings,
)
from services.action.language_model.data.repository import (
    InMemoryLanguageModelCallAuditRepository,
    InMemoryLanguageModelTurnCacheHopRepository,
)
from services.action.language_model.domain import (
    ChatResponse,
    ChatToolCall,
    ChatWithToolsResponse,
    EmbeddingVector,
    HealthStatus,
    InferenceRequest,
    LanguageModelCallAuditRow,
    LanguageModelTurnCacheHopRow,
)
from services.action.language_model.interfaces import (
    LanguageModelCallAuditRepository,
    LanguageModelTurnCacheHopRepository,
)
from services.action.language_model.service import LanguageModelService
from services.action.language_model.validation import (
    ChatBatchRequest,
    ChatRequest,
    ChatWithToolsRequest,
    EmbedBatchRequest,
    EmbedRequest,
    EmbeddingProfile,
    ReasoningLevel,
)

_LOGGER = get_logger(__name__)
_CACHE_WRITE_PREMIUM_MULTIPLIER = 0.25
_CACHE_READ_DISCOUNT_MULTIPLIER = 0.90


@dataclass(frozen=True)
class _ResolvedProfile:
    """One resolved provider/model pair for downstream adapter calls."""

    provider: str
    model: str
    dimensions: int | None = None


class DefaultLanguageModelService(LanguageModelService):
    """Default LMS implementation backed by the native LLM adapter resource."""

    def __init__(
        self,
        *,
        settings: LanguageModelServiceSettings,
        adapter: LlmAdapter,
        audit_repository: LanguageModelCallAuditRepository | None = None,
        turn_cache_hop_repository: LanguageModelTurnCacheHopRepository | None = None,
    ) -> None:
        self._settings = settings
        self._adapter = adapter
        self._audit_repository = (
            InMemoryLanguageModelCallAuditRepository()
            if audit_repository is None
            else audit_repository
        )
        self._turn_cache_hop_repository = (
            InMemoryLanguageModelTurnCacheHopRepository()
            if turn_cache_hop_repository is None
            else turn_cache_hop_repository
        )

    @classmethod
    def from_settings(
        cls, settings: CoreRuntimeSettings
    ) -> "DefaultLanguageModelService":
        """Build LMS and owned adapter from typed root settings."""
        service_settings = resolve_language_model_service_settings(settings)
        adapter_settings = resolve_llm_adapter_settings(settings)
        return cls(
            settings=service_settings,
            adapter=HttpLlmAdapter(settings=adapter_settings),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def chat(
        self,
        *,
        meta: EnvelopeMeta,
        system_prompt: str = "",
        prompt: str,
        profile: ReasoningLevel = ReasoningLevel.STANDARD,
    ) -> Envelope[ChatResponse]:
        """Generate one chat completion using resolved model profile."""
        request, errors = self._validate_request(
            meta=meta,
            model=ChatRequest,
            payload={
                "system_prompt": system_prompt,
                "prompt": prompt,
                "profile": profile,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        resolved = self._resolve_chat_profile(profile=request.profile)
        try:
            result = self._adapter.chat(
                provider=resolved.provider,
                model=resolved.model,
                system_prompt=request.system_prompt,
                prompt=request.prompt,
            )
        except AdapterDependencyError as exc:
            self._append_call_audit(
                meta=meta,
                provider=resolved.provider,
                model=resolved.model,
                profile=request.profile.value,
                operation="chat",
                request_phase="initial",
                outcome_kind="error",
                raw_call=getattr(exc, "raw_call", None),
                error_message=str(exc) or "llm dependency failure",
            )
            return failure(
                meta=meta,
                errors=[
                    dependency_error(
                        str(exc) or "llm dependency failure",
                        code=codes.DEPENDENCY_UNAVAILABLE,
                        metadata={"adapter": "adapter_llm"},
                    )
                ],
            )
        except AdapterInternalError as exc:
            self._append_call_audit(
                meta=meta,
                provider=resolved.provider,
                model=resolved.model,
                profile=request.profile.value,
                operation="chat",
                request_phase="initial",
                outcome_kind="error",
                raw_call=getattr(exc, "raw_call", None),
                error_message=str(exc) or "llm adapter internal failure",
            )
            return failure(
                meta=meta,
                errors=[
                    internal_error(
                        str(exc) or "llm adapter internal failure",
                        code=codes.INTERNAL_ERROR,
                        metadata={"adapter": "adapter_llm"},
                    )
                ],
            )

        self._append_call_audit(
            meta=meta,
            provider=result.provider,
            model=result.model,
            profile=request.profile.value,
            operation="chat",
            request_phase="initial",
            outcome_kind="final",
            raw_call=result.raw_call,
        )
        return success(
            meta=meta,
            payload=ChatResponse(
                text=result.text,
                provider=result.provider,
                model=result.model,
            ),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def chat_batch(
        self,
        *,
        meta: EnvelopeMeta,
        prompts: Sequence[str],
        profile: ReasoningLevel = ReasoningLevel.STANDARD,
    ) -> Envelope[list[ChatResponse]]:
        """Generate a batch of chat completions with one profile."""
        request, errors = self._validate_request(
            meta=meta,
            model=ChatBatchRequest,
            payload={"prompts": prompts, "profile": profile},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        resolved = self._resolve_chat_profile(profile=request.profile)
        try:
            results = self._adapter.chat_batch(
                provider=resolved.provider,
                model=resolved.model,
                prompts=request.prompts,
            )
        except AdapterDependencyError as exc:
            self._append_call_audit(
                meta=meta,
                provider=resolved.provider,
                model=resolved.model,
                profile=request.profile.value,
                operation="chat_batch",
                request_phase="initial",
                outcome_kind="error",
                raw_call=getattr(exc, "raw_call", None),
                error_message=str(exc) or "llm dependency failure",
            )
            return failure(
                meta=meta,
                errors=[
                    dependency_error(
                        str(exc) or "llm dependency failure",
                        code=codes.DEPENDENCY_UNAVAILABLE,
                        metadata={"adapter": "adapter_llm"},
                    )
                ],
            )
        except AdapterInternalError as exc:
            self._append_call_audit(
                meta=meta,
                provider=resolved.provider,
                model=resolved.model,
                profile=request.profile.value,
                operation="chat_batch",
                request_phase="initial",
                outcome_kind="error",
                raw_call=getattr(exc, "raw_call", None),
                error_message=str(exc) or "llm adapter internal failure",
            )
            return failure(
                meta=meta,
                errors=[
                    internal_error(
                        str(exc) or "llm adapter internal failure",
                        code=codes.INTERNAL_ERROR,
                        metadata={"adapter": "adapter_llm"},
                    )
                ],
            )

        first = results[0] if results else None
        self._append_call_audit(
            meta=meta,
            provider="" if first is None else first.provider,
            model="" if first is None else first.model,
            profile=request.profile.value,
            operation="chat_batch",
            request_phase="initial",
            outcome_kind="final",
            raw_call=None if first is None else first.raw_call,
        )
        return success(
            meta=meta,
            payload=[
                ChatResponse(
                    text=item.text,
                    provider=item.provider,
                    model=item.model,
                )
                for item in results
            ],
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def chat_with_tools(
        self,
        *,
        meta: EnvelopeMeta,
        inference_request: InferenceRequest,
    ) -> Envelope[ChatWithToolsResponse]:
        """Generate one tool-capable completion using the resolved chat profile."""
        request, errors = self._validate_request(
            meta=meta,
            model=ChatWithToolsRequest,
            payload={"inference_request": inference_request},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        effective_profile = (
            ReasoningLevel.STANDARD
            if request.inference_request.controls.profile is None
            else ReasoningLevel(request.inference_request.controls.profile)
        )
        resolved = self._resolve_chat_profile(profile=effective_profile)
        request_phase = _request_phase_for_inference_request(request.inference_request)
        try:
            result = self._adapter.chat_with_tools(
                provider=resolved.provider,
                model=resolved.model,
                inference_request=request.inference_request,
            )
        except AdapterDependencyError as exc:
            audit_row = self._append_call_audit(
                meta=meta,
                provider=resolved.provider,
                model=resolved.model,
                profile=effective_profile.value,
                operation="chat_with_tools",
                request_phase=request_phase,
                outcome_kind="error",
                raw_call=getattr(exc, "raw_call", None),
                error_message=str(exc) or "llm dependency failure",
            )
            self._append_turn_cache_hop(
                audit_row=audit_row,
                inference_request=request.inference_request,
                raw_call=getattr(exc, "raw_call", None),
            )
            return failure(
                meta=meta,
                errors=[
                    dependency_error(
                        str(exc) or "llm dependency failure",
                        code=codes.DEPENDENCY_UNAVAILABLE,
                        metadata={"adapter": "adapter_llm"},
                    )
                ],
            )
        except AdapterInternalError as exc:
            audit_row = self._append_call_audit(
                meta=meta,
                provider=resolved.provider,
                model=resolved.model,
                profile=effective_profile.value,
                operation="chat_with_tools",
                request_phase=request_phase,
                outcome_kind="error",
                raw_call=getattr(exc, "raw_call", None),
                error_message=str(exc) or "llm adapter internal failure",
            )
            self._append_turn_cache_hop(
                audit_row=audit_row,
                inference_request=request.inference_request,
                raw_call=getattr(exc, "raw_call", None),
            )
            return failure(
                meta=meta,
                errors=[
                    internal_error(
                        str(exc) or "llm adapter internal failure",
                        code=codes.INTERNAL_ERROR,
                        metadata={"adapter": "adapter_llm"},
                    )
                ],
            )

        if (
            not request.inference_request.controls.allow_text_output
            and len(result.tool_calls) == 0
        ):
            audit_row = self._append_call_audit(
                meta=meta,
                provider=result.provider,
                model=result.model,
                profile=effective_profile.value,
                operation="chat_with_tools",
                request_phase=request_phase,
                outcome_kind="error",
                raw_call=result.raw_call,
                finish_reason=result.finish_reason,
                error_message="tool-capable model response did not include any tool calls",
            )
            self._append_turn_cache_hop(
                audit_row=audit_row,
                inference_request=request.inference_request,
                raw_call=result.raw_call,
            )
            return failure(
                meta=meta,
                errors=[
                    internal_error(
                        "tool-capable model response did not include any tool calls",
                        code=codes.INTERNAL_ERROR,
                        metadata={"adapter": "adapter_llm"},
                    )
                ],
            )

        audit_row = self._append_call_audit(
            meta=meta,
            provider=result.provider,
            model=result.model,
            profile=effective_profile.value,
            operation="chat_with_tools",
            request_phase=request_phase,
            outcome_kind=_tool_chat_outcome_kind(result=result),
            raw_call=result.raw_call,
            finish_reason=result.finish_reason,
        )
        self._append_turn_cache_hop(
            audit_row=audit_row,
            inference_request=request.inference_request,
            raw_call=result.raw_call,
        )
        return success(
            meta=meta,
            payload=ChatWithToolsResponse(
                text=result.text,
                tool_calls=tuple(
                    ChatToolCall.model_validate(item.model_dump(mode="python"))
                    for item in result.tool_calls
                ),
                provider=result.provider,
                model=result.model,
                finish_reason=result.finish_reason,
            ),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def embed(
        self,
        *,
        meta: EnvelopeMeta,
        text: str,
        profile: EmbeddingProfile = EmbeddingProfile.DOCUMENT_EMBEDDING,
    ) -> Envelope[EmbeddingVector]:
        """Generate one embedding vector using embedding profile."""
        request, errors = self._validate_request(
            meta=meta,
            model=EmbedRequest,
            payload={"text": text, "profile": profile},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        resolved = self._resolve_embed_profile(profile=request.profile)
        try:
            result = self._adapter.embed(
                provider=resolved.provider,
                model=resolved.model,
                text=request.text,
                dimensions=resolved.dimensions,
            )
        except AdapterDependencyError as exc:
            self._append_call_audit(
                meta=meta,
                provider=resolved.provider,
                model=resolved.model,
                profile=request.profile.value,
                operation="embed",
                request_phase="embedding",
                outcome_kind="error",
                raw_call=getattr(exc, "raw_call", None),
                error_message=str(exc) or "llm dependency failure",
            )
            return failure(
                meta=meta,
                errors=[
                    dependency_error(
                        str(exc) or "llm dependency failure",
                        code=codes.DEPENDENCY_UNAVAILABLE,
                        metadata={"adapter": "adapter_llm"},
                    )
                ],
            )
        except AdapterInternalError as exc:
            self._append_call_audit(
                meta=meta,
                provider=resolved.provider,
                model=resolved.model,
                profile=request.profile.value,
                operation="embed",
                request_phase="embedding",
                outcome_kind="error",
                raw_call=getattr(exc, "raw_call", None),
                error_message=str(exc) or "llm adapter internal failure",
            )
            return failure(
                meta=meta,
                errors=[
                    internal_error(
                        str(exc) or "llm adapter internal failure",
                        code=codes.INTERNAL_ERROR,
                        metadata={"adapter": "adapter_llm"},
                    )
                ],
            )

        self._append_call_audit(
            meta=meta,
            provider=result.provider,
            model=result.model,
            profile=request.profile.value,
            operation="embed",
            request_phase="embedding",
            outcome_kind="embedding",
            raw_call=result.raw_call,
        )
        return success(
            meta=meta,
            payload=EmbeddingVector(
                values=result.values,
                provider=result.provider,
                model=result.model,
            ),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def embed_batch(
        self,
        *,
        meta: EnvelopeMeta,
        texts: Sequence[str],
        profile: EmbeddingProfile = EmbeddingProfile.DOCUMENT_EMBEDDING,
    ) -> Envelope[list[EmbeddingVector]]:
        """Generate a batch of embedding vectors."""
        request, errors = self._validate_request(
            meta=meta,
            model=EmbedBatchRequest,
            payload={"texts": texts, "profile": profile},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        resolved = self._resolve_embed_profile(profile=request.profile)
        try:
            results = self._adapter.embed_batch(
                provider=resolved.provider,
                model=resolved.model,
                texts=request.texts,
                dimensions=resolved.dimensions,
            )
        except AdapterDependencyError as exc:
            self._append_call_audit(
                meta=meta,
                provider=resolved.provider,
                model=resolved.model,
                profile=request.profile.value,
                operation="embed_batch",
                request_phase="embedding",
                outcome_kind="error",
                raw_call=getattr(exc, "raw_call", None),
                error_message=str(exc) or "llm dependency failure",
            )
            return failure(
                meta=meta,
                errors=[
                    dependency_error(
                        str(exc) or "llm dependency failure",
                        code=codes.DEPENDENCY_UNAVAILABLE,
                        metadata={"adapter": "adapter_llm"},
                    )
                ],
            )
        except AdapterInternalError as exc:
            self._append_call_audit(
                meta=meta,
                provider=resolved.provider,
                model=resolved.model,
                profile=request.profile.value,
                operation="embed_batch",
                request_phase="embedding",
                outcome_kind="error",
                raw_call=getattr(exc, "raw_call", None),
                error_message=str(exc) or "llm adapter internal failure",
            )
            return failure(
                meta=meta,
                errors=[
                    internal_error(
                        str(exc) or "llm adapter internal failure",
                        code=codes.INTERNAL_ERROR,
                        metadata={"adapter": "adapter_llm"},
                    )
                ],
            )

        first = results[0] if results else None
        self._append_call_audit(
            meta=meta,
            provider="" if first is None else first.provider,
            model="" if first is None else first.model,
            profile=request.profile.value,
            operation="embed_batch",
            request_phase="embedding",
            outcome_kind="embedding",
            raw_call=None if first is None else first.raw_call,
        )
        return success(
            meta=meta,
            payload=[
                EmbeddingVector(
                    values=item.values,
                    provider=item.provider,
                    model=item.model,
                )
                for item in results
            ],
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        """Return LMS-level readiness with adapter probe result."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )

        result = self._adapter.health()
        return success(
            meta=meta,
            payload=HealthStatus(
                service_ready=True,
                adapter_ready=result.adapter_ready,
                detail=result.detail,
            ),
        )

    def _resolve_chat_profile(self, *, profile: ReasoningLevel) -> _ResolvedProfile:
        """Resolve one chat reasoning level to concrete provider/model settings."""
        if profile is ReasoningLevel.QUICK:
            return _from_settings(self._settings.quick)
        if profile is ReasoningLevel.DEEP:
            return _from_settings(self._settings.deep)
        return _from_settings(self._settings.standard)

    def _resolve_embed_profile(self, *, profile: EmbeddingProfile) -> _ResolvedProfile:
        """Resolve embedding profile to concrete provider/model settings."""
        if profile is EmbeddingProfile.CAPABILITY_EMBEDDING:
            return _from_settings(self._settings.capability_embedding)
        return _from_settings(self._settings.document_embedding)

    def _validate_request(
        self,
        *,
        meta: EnvelopeMeta,
        model: type[BaseModel],
        payload: dict[str, Any],
    ) -> tuple[BaseModel | None, list[ErrorDetail]]:
        """Validate metadata and request payload with stable errors."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return None, [validation_error(str(exc), code=codes.INVALID_ARGUMENT)]

        try:
            validated = model.model_validate(payload)
        except ValidationError as exc:
            issue = exc.errors()[0]
            field = ".".join(str(item) for item in issue.get("loc", ()))
            field_name = field if field else "payload"
            message = f"{field_name}: {issue.get('msg', 'invalid value')}"
            return None, [validation_error(message, code=codes.INVALID_ARGUMENT)]

        return validated, []

    def _append_call_audit(
        self,
        *,
        meta: EnvelopeMeta,
        provider: str,
        model: str,
        profile: str,
        operation: str,
        request_phase: str,
        outcome_kind: str,
        raw_call: AdapterProviderCallAudit | None,
        finish_reason: str = "",
        error_message: str = "",
    ) -> LanguageModelCallAuditRow:
        """Append one provider-bound LMS call audit row and return the stored row."""
        row = LanguageModelCallAuditRow(
            envelope_id=meta.envelope_id,
            trace_id=meta.trace_id,
            parent_id=meta.parent_id,
            source=meta.source,
            principal=meta.principal,
            provider=provider,
            model=model,
            profile=profile,
            operation=operation,
            request_phase=request_phase,
            outcome_kind=outcome_kind,
            call_index=self._audit_repository.next_call_index(trace_id=meta.trace_id),
            finish_reason=finish_reason,
            error_message=error_message,
            request_json=None if raw_call is None else _provider_request_json(raw_call),
            response_json=None
            if raw_call is None
            else _provider_response_json(raw_call),
            created_at=datetime.now(UTC),
        )
        self._audit_repository.append(row=row)
        return row

    def _append_turn_cache_hop(
        self,
        *,
        audit_row: LanguageModelCallAuditRow,
        inference_request: InferenceRequest,
        raw_call: AdapterProviderCallAudit | None,
    ) -> None:
        """Append one per-hop cache telemetry row for a tool-capable LMS call."""
        request_json = None if raw_call is None else _provider_request_json(raw_call)
        response_json = None if raw_call is None else _provider_response_json(raw_call)
        cache_control_count = _count_provider_cache_control_blocks(request_json)
        cache_creation_input_tokens, cache_read_input_tokens = _provider_cache_usage(
            response_json
        )
        placed_cachepoint_ordinal = _placed_cachepoint_ordinal(
            inference_request=inference_request,
            cache_control_count=cache_control_count,
        )
        row = LanguageModelTurnCacheHopRow(
            trace_id=audit_row.trace_id,
            hop_ordinal=self._turn_cache_hop_repository.next_hop_ordinal(
                trace_id=audit_row.trace_id
            ),
            call_index=audit_row.call_index,
            envelope_id=audit_row.envelope_id,
            provider=audit_row.provider,
            model=audit_row.model,
            profile=audit_row.profile,
            placed_cachepoint_ordinal=placed_cachepoint_ordinal,
            cp0_active=cache_control_count >= 1,
            cp1_active=cache_control_count >= 2,
            cp2_active=cache_control_count >= 3,
            cp3_active=cache_control_count >= 4,
            active_cachepoint_count=cache_control_count,
            provider_cache_control_block_count=cache_control_count,
            cache_creation_input_tokens=cache_creation_input_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
            estimated_write_premium_token_equiv=(
                _CACHE_WRITE_PREMIUM_MULTIPLIER * cache_creation_input_tokens
            ),
            estimated_read_savings_token_equiv=(
                _CACHE_READ_DISCOUNT_MULTIPLIER * cache_read_input_tokens
            ),
            estimated_net_token_equiv=(
                (_CACHE_READ_DISCOUNT_MULTIPLIER * cache_read_input_tokens)
                - (_CACHE_WRITE_PREMIUM_MULTIPLIER * cache_creation_input_tokens)
            ),
            created_at=audit_row.created_at,
        )
        self._turn_cache_hop_repository.append(row=row)


def _from_settings(
    settings: LanguageModelProfileSettings | LanguageModelEmbeddingProfileSettings,
) -> _ResolvedProfile:
    """Convert required profile settings into resolved call-time tuple."""
    dimensions = (
        settings.dimensions
        if isinstance(settings, LanguageModelEmbeddingProfileSettings)
        else None
    )
    return _ResolvedProfile(
        provider=settings.provider,
        model=settings.model,
        dimensions=dimensions,
    )


def _request_phase_for_inference_request(request: InferenceRequest) -> str:
    """Classify one tool-capable request as initial or tool follow-up."""
    for event in request.live_events:
        if event.kind in {"tool_call_batch", "tool_result_batch"}:
            return "tool_followup"
    return "initial"


def _tool_chat_outcome_kind(*, result: Any) -> str:
    """Classify one tool-capable model response for audit reporting."""
    has_tool_calls = len(result.tool_calls) > 0
    has_text = isinstance(result.text, str) and result.text.strip() != ""
    if has_tool_calls and has_text:
        return "mixed"
    if has_tool_calls:
        return "tool_call"
    if has_text:
        return "final"
    return "empty"


def _provider_request_json(raw_call: AdapterProviderCallAudit) -> dict[str, object]:
    """Serialize provider request artifacts into one JSON document."""
    return {
        "api_base": raw_call.request_api_base,
        "headers": raw_call.request_headers,
        "body": raw_call.request_body,
    }


def _provider_response_json(raw_call: AdapterProviderCallAudit) -> dict[str, object]:
    """Serialize provider response artifacts into one JSON document."""
    return {"body": raw_call.response_body}


def _count_provider_cache_control_blocks(request_json: object | None) -> int:
    """Count explicit provider cache-control blocks in one serialized request."""
    if not isinstance(request_json, dict):
        return 0
    body = request_json.get("body")
    if not isinstance(body, dict):
        return 0

    count = 0
    system = body.get("system")
    if isinstance(system, list):
        for block in system:
            if isinstance(block, dict) and "cache_control" in block:
                count += 1

    messages = body.get("messages")
    if not isinstance(messages, list):
        return count
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and "cache_control" in block:
                count += 1
    return count


def _provider_cache_usage(response_json: object | None) -> tuple[int, int]:
    """Extract provider-reported cache write and read usage token counts."""
    if not isinstance(response_json, dict):
        return 0, 0
    body = response_json.get("body")
    if not isinstance(body, dict):
        return 0, 0
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return 0, 0
    created = usage.get("cache_creation_input_tokens", 0)
    read = usage.get("cache_read_input_tokens", 0)
    try:
        created_tokens = int(created)
    except (TypeError, ValueError):
        created_tokens = 0
    try:
        read_tokens = int(read)
    except (TypeError, ValueError):
        read_tokens = 0
    return max(0, created_tokens), max(0, read_tokens)


def _placed_cachepoint_ordinal(
    *,
    inference_request: InferenceRequest,
    cache_control_count: int,
) -> int | None:
    """Return the cachepoint ordinal newly placed for one hop, when present."""
    if cache_control_count <= 0:
        return None
    if (
        len(inference_request.live_events) == 0
        and inference_request.cache.mode == "explicit"
    ):
        return 0
    latest_event = (
        inference_request.live_events[-1] if inference_request.live_events else None
    )
    if (
        latest_event is not None
        and latest_event.kind == "tool_result_batch"
        and latest_event.cache_after
    ):
        return min(cache_control_count - 1, 3)
    return None
