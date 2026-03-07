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
from resources.adapters.litellm import (
    AdapterChatMessage,
    AdapterChatToolDefinition,
    AdapterDependencyError,
    AdapterInternalError,
    AdapterProviderCallAudit,
    LiteLlmAdapter,
    LiteLlmLibraryAdapter,
    resolve_litellm_adapter_settings,
)
from services.action.language_model.component import SERVICE_COMPONENT_ID
from services.action.language_model.config import (
    LanguageModelProfileSettings,
    LanguageModelServiceSettings,
    resolve_language_model_service_settings,
)
from services.action.language_model.data.repository import (
    InMemoryLanguageModelCallAuditRepository,
)
from services.action.language_model.domain import (
    ChatMessage,
    ChatResponse,
    ChatToolCall,
    ChatToolDefinition,
    ChatWithToolsResponse,
    EmbeddingVector,
    HealthStatus,
    LanguageModelCallAuditRow,
)
from services.action.language_model.interfaces import LanguageModelCallAuditRepository
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


@dataclass(frozen=True)
class _ResolvedProfile:
    """One resolved provider/model pair for downstream adapter calls."""

    provider: str
    model: str


class DefaultLanguageModelService(LanguageModelService):
    """Default LMS implementation backed by a LiteLLM adapter resource."""

    def __init__(
        self,
        *,
        settings: LanguageModelServiceSettings,
        adapter: LiteLlmAdapter,
        audit_repository: LanguageModelCallAuditRepository | None = None,
    ) -> None:
        self._settings = settings
        self._adapter = adapter
        self._audit_repository = (
            InMemoryLanguageModelCallAuditRepository()
            if audit_repository is None
            else audit_repository
        )

    @classmethod
    def from_settings(
        cls, settings: CoreRuntimeSettings
    ) -> "DefaultLanguageModelService":
        """Build LMS and owned adapter from typed root settings."""
        service_settings = resolve_language_model_service_settings(settings)
        adapter_settings = resolve_litellm_adapter_settings(settings)
        return cls(
            settings=service_settings,
            adapter=LiteLlmLibraryAdapter(settings=adapter_settings),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def chat(
        self,
        *,
        meta: EnvelopeMeta,
        prompt: str,
        profile: ReasoningLevel = ReasoningLevel.STANDARD,
    ) -> Envelope[ChatResponse]:
        """Generate one chat completion using resolved model profile."""
        request, errors = self._validate_request(
            meta=meta,
            model=ChatRequest,
            payload={"prompt": prompt, "profile": profile},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        resolved = self._resolve_chat_profile(profile=request.profile)
        try:
            result = self._adapter.chat(
                provider=resolved.provider,
                model=resolved.model,
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
                error_message=str(exc) or "litellm dependency failure",
            )
            return failure(
                meta=meta,
                errors=[
                    dependency_error(
                        str(exc) or "litellm dependency failure",
                        code=codes.DEPENDENCY_UNAVAILABLE,
                        metadata={"adapter": "adapter_litellm"},
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
                error_message=str(exc) or "litellm adapter internal failure",
            )
            return failure(
                meta=meta,
                errors=[
                    internal_error(
                        str(exc) or "litellm adapter internal failure",
                        code=codes.INTERNAL_ERROR,
                        metadata={"adapter": "adapter_litellm"},
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
                error_message=str(exc) or "litellm dependency failure",
            )
            return failure(
                meta=meta,
                errors=[
                    dependency_error(
                        str(exc) or "litellm dependency failure",
                        code=codes.DEPENDENCY_UNAVAILABLE,
                        metadata={"adapter": "adapter_litellm"},
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
                error_message=str(exc) or "litellm adapter internal failure",
            )
            return failure(
                meta=meta,
                errors=[
                    internal_error(
                        str(exc) or "litellm adapter internal failure",
                        code=codes.INTERNAL_ERROR,
                        metadata={"adapter": "adapter_litellm"},
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
        messages: Sequence[ChatMessage],
        tools: Sequence[ChatToolDefinition] = (),
        tool_choice: str | dict[str, object] | None = None,
        parallel_tool_calls: bool | None = None,
        allow_text_output: bool = True,
        profile: ReasoningLevel = ReasoningLevel.STANDARD,
    ) -> Envelope[ChatWithToolsResponse]:
        """Generate one tool-capable completion using the resolved chat profile."""
        request, errors = self._validate_request(
            meta=meta,
            model=ChatWithToolsRequest,
            payload={
                "messages": [
                    item.model_dump(mode="python")
                    if isinstance(item, BaseModel)
                    else item
                    for item in messages
                ],
                "tools": [
                    item.model_dump(mode="python")
                    if isinstance(item, BaseModel)
                    else item
                    for item in tools
                ],
                "tool_choice": tool_choice,
                "parallel_tool_calls": parallel_tool_calls,
                "allow_text_output": allow_text_output,
                "profile": profile,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        resolved = self._resolve_chat_profile(profile=request.profile)
        request_phase = _request_phase_for_messages(request.messages)
        try:
            result = self._adapter.chat_with_tools(
                provider=resolved.provider,
                model=resolved.model,
                messages=[
                    AdapterChatMessage.model_validate(item.model_dump(mode="python"))
                    for item in request.messages
                ],
                tools=[
                    AdapterChatToolDefinition.model_validate(
                        item.model_dump(mode="python")
                    )
                    for item in request.tools
                ],
                tool_choice=request.tool_choice,
                parallel_tool_calls=request.parallel_tool_calls,
            )
        except AdapterDependencyError as exc:
            self._append_call_audit(
                meta=meta,
                provider=resolved.provider,
                model=resolved.model,
                profile=request.profile.value,
                operation="chat_with_tools",
                request_phase=request_phase,
                outcome_kind="error",
                raw_call=getattr(exc, "raw_call", None),
                error_message=str(exc) or "litellm dependency failure",
            )
            return failure(
                meta=meta,
                errors=[
                    dependency_error(
                        str(exc) or "litellm dependency failure",
                        code=codes.DEPENDENCY_UNAVAILABLE,
                        metadata={"adapter": "adapter_litellm"},
                    )
                ],
            )
        except AdapterInternalError as exc:
            self._append_call_audit(
                meta=meta,
                provider=resolved.provider,
                model=resolved.model,
                profile=request.profile.value,
                operation="chat_with_tools",
                request_phase=request_phase,
                outcome_kind="error",
                raw_call=getattr(exc, "raw_call", None),
                error_message=str(exc) or "litellm adapter internal failure",
            )
            return failure(
                meta=meta,
                errors=[
                    internal_error(
                        str(exc) or "litellm adapter internal failure",
                        code=codes.INTERNAL_ERROR,
                        metadata={"adapter": "adapter_litellm"},
                    )
                ],
            )

        if not request.allow_text_output and len(result.tool_calls) == 0:
            self._append_call_audit(
                meta=meta,
                provider=result.provider,
                model=result.model,
                profile=request.profile.value,
                operation="chat_with_tools",
                request_phase=request_phase,
                outcome_kind="error",
                raw_call=result.raw_call,
                finish_reason=result.finish_reason,
                error_message="tool-capable model response did not include any tool calls",
            )
            return failure(
                meta=meta,
                errors=[
                    internal_error(
                        "tool-capable model response did not include any tool calls",
                        code=codes.INTERNAL_ERROR,
                        metadata={"adapter": "adapter_litellm"},
                    )
                ],
            )

        self._append_call_audit(
            meta=meta,
            provider=result.provider,
            model=result.model,
            profile=request.profile.value,
            operation="chat_with_tools",
            request_phase=request_phase,
            outcome_kind=_tool_chat_outcome_kind(result=result),
            raw_call=result.raw_call,
            finish_reason=result.finish_reason,
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
        profile: EmbeddingProfile = EmbeddingProfile.EMBEDDING,
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
                error_message=str(exc) or "litellm dependency failure",
            )
            return failure(
                meta=meta,
                errors=[
                    dependency_error(
                        str(exc) or "litellm dependency failure",
                        code=codes.DEPENDENCY_UNAVAILABLE,
                        metadata={"adapter": "adapter_litellm"},
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
                error_message=str(exc) or "litellm adapter internal failure",
            )
            return failure(
                meta=meta,
                errors=[
                    internal_error(
                        str(exc) or "litellm adapter internal failure",
                        code=codes.INTERNAL_ERROR,
                        metadata={"adapter": "adapter_litellm"},
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
        profile: EmbeddingProfile = EmbeddingProfile.EMBEDDING,
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
                error_message=str(exc) or "litellm dependency failure",
            )
            return failure(
                meta=meta,
                errors=[
                    dependency_error(
                        str(exc) or "litellm dependency failure",
                        code=codes.DEPENDENCY_UNAVAILABLE,
                        metadata={"adapter": "adapter_litellm"},
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
                error_message=str(exc) or "litellm adapter internal failure",
            )
            return failure(
                meta=meta,
                errors=[
                    internal_error(
                        str(exc) or "litellm adapter internal failure",
                        code=codes.INTERNAL_ERROR,
                        metadata={"adapter": "adapter_litellm"},
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
        del profile
        return _from_settings(self._settings.embedding)

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
    ) -> None:
        """Append one provider-bound LMS call audit row."""
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


def _from_settings(settings: LanguageModelProfileSettings) -> _ResolvedProfile:
    """Convert required profile settings into resolved call-time tuple."""
    return _ResolvedProfile(provider=settings.provider, model=settings.model)


def _request_phase_for_messages(messages: Sequence[ChatMessage]) -> str:
    """Classify one tool-capable request as initial or tool follow-up."""
    for message in messages:
        if message.role == "tool":
            return "tool_followup"
        if message.role == "assistant" and len(message.tool_calls) > 0:
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
