"""Concrete Language Model Service implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from pydantic import BaseModel, ValidationError
from packages.brain_shared.config import BrainSettings
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
    AdapterDependencyError,
    AdapterInternalError,
    LiteLlmLibraryAdapter,
    LiteLlmAdapter,
    resolve_litellm_adapter_settings,
)
from services.action.language_model.component import SERVICE_COMPONENT_ID
from services.action.language_model.config import (
    LanguageModelProfileSettings,
    LanguageModelServiceSettings,
    resolve_language_model_service_settings,
)
from services.action.language_model.domain import (
    ChatResponse,
    EmbeddingVector,
    HealthStatus,
)
from services.action.language_model.service import LanguageModelService
from services.action.language_model.validation import (
    ChatBatchRequest,
    ChatRequest,
    EmbeddingProfile,
    EmbedBatchRequest,
    EmbedRequest,
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
    ) -> None:
        self._settings = settings
        self._adapter = adapter

    @classmethod
    def from_settings(cls, settings: BrainSettings) -> "DefaultLanguageModelService":
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


def _from_settings(settings: LanguageModelProfileSettings) -> _ResolvedProfile:
    """Convert required profile settings into resolved call-time tuple."""
    return _ResolvedProfile(provider=settings.provider, model=settings.model)
