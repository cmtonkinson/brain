"""Pydantic settings for the Language Model Service."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from packages.brain_shared.config import CoreRuntimeSettings, resolve_component_settings
from services.action.language_model.component import SERVICE_COMPONENT_ID

DEFAULT_DOCUMENT_EMBEDDING_PROFILE = {
    "provider": "ollama",
    "model": "mxbai-embed-large",
    "dimensions": 1024,
}
DEFAULT_CAPABILITY_EMBEDDING_PROFILE = {
    "provider": "ollama",
    "model": "mxbai-embed-large",
    "dimensions": 1024,
}
DEFAULT_STANDARD_PROFILE = {
    "provider": "anthropic",
    "model": "claude-sonnet-4-6-20251001",
}
DEFAULT_QUICK_PROFILE = {
    "provider": "anthropic",
    "model": "claude-haiku-4-5-20251001",
}
DEFAULT_DEEP_PROFILE = {
    "provider": "anthropic",
    "model": "claude-opus-4-7",
}


class LanguageModelProfileSettings(BaseModel):
    """Resolved model selector for one profile."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    model: str


class LanguageModelEmbeddingProfileSettings(BaseModel):
    """Resolved model selector for one embedding profile."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    model: str
    dimensions: int = Field(gt=0)


class LanguageModelOptionalProfileSettings(BaseModel):
    """Optional model selector for fallback-enabled profiles."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = ""
    model: str = ""


class LanguageModelServiceSettings(BaseModel):
    """Resolved service settings defining chat and embedding model profiles."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_embedding: LanguageModelEmbeddingProfileSettings = (
        LanguageModelEmbeddingProfileSettings(**DEFAULT_DOCUMENT_EMBEDDING_PROFILE)
    )
    capability_embedding: LanguageModelEmbeddingProfileSettings = (
        LanguageModelEmbeddingProfileSettings(**DEFAULT_CAPABILITY_EMBEDDING_PROFILE)
    )
    quick: LanguageModelProfileSettings = LanguageModelProfileSettings(
        **DEFAULT_QUICK_PROFILE
    )
    standard: LanguageModelProfileSettings = LanguageModelProfileSettings(
        **DEFAULT_STANDARD_PROFILE
    )
    deep: LanguageModelProfileSettings = LanguageModelProfileSettings(
        **DEFAULT_DEEP_PROFILE
    )


class _LanguageModelServiceSettingsInput(BaseModel):
    """Raw config shape supporting optional fallback-enabled reasoning levels."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_embedding: LanguageModelEmbeddingProfileSettings = (
        LanguageModelEmbeddingProfileSettings(**DEFAULT_DOCUMENT_EMBEDDING_PROFILE)
    )
    capability_embedding: LanguageModelEmbeddingProfileSettings = (
        LanguageModelEmbeddingProfileSettings(**DEFAULT_CAPABILITY_EMBEDDING_PROFILE)
    )
    quick: LanguageModelOptionalProfileSettings = LanguageModelOptionalProfileSettings(
        **DEFAULT_QUICK_PROFILE
    )
    standard: LanguageModelProfileSettings = LanguageModelProfileSettings(
        **DEFAULT_STANDARD_PROFILE
    )
    deep: LanguageModelOptionalProfileSettings = LanguageModelOptionalProfileSettings(
        **DEFAULT_DEEP_PROFILE
    )


def resolve_language_model_service_settings(
    settings: CoreRuntimeSettings,
) -> LanguageModelServiceSettings:
    """Resolve service settings from ``service.language_model``."""
    raw = resolve_component_settings(
        settings=settings,
        component_id=str(SERVICE_COMPONENT_ID),
        model=_LanguageModelServiceSettingsInput,
    )
    return LanguageModelServiceSettings(
        document_embedding=raw.document_embedding,
        capability_embedding=raw.capability_embedding,
        quick=_resolve_chat_fallback(
            candidate=raw.quick,
            fallback=raw.standard,
        ),
        standard=raw.standard,
        deep=_resolve_chat_fallback(
            candidate=raw.deep,
            fallback=raw.standard,
        ),
    )


def _resolve_chat_fallback(
    *,
    candidate: LanguageModelOptionalProfileSettings,
    fallback: LanguageModelProfileSettings,
) -> LanguageModelProfileSettings:
    """Resolve one optional chat profile with per-field fallback to standard."""
    provider = candidate.provider.strip()
    model = candidate.model.strip()
    return LanguageModelProfileSettings(
        provider=provider if provider != "" else fallback.provider,
        model=model if model != "" else fallback.model,
    )
