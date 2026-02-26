"""Pydantic settings for the Language Model Service."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from packages.brain_shared.config import BrainSettings, resolve_component_settings
from services.action.language_model.component import SERVICE_COMPONENT_ID

DEFAULT_EMBEDDING_PROFILE = {
    "provider": "ollama",
    "model": "mxbai-embed-large",
}
DEFAULT_STANDARD_PROFILE = {
    "provider": "ollama",
    "model": "gpt-oss:20b",
}


class LanguageModelProfileSettings(BaseModel):
    """Resolved model selector for one profile."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    model: str


class LanguageModelOptionalProfileSettings(BaseModel):
    """Optional model selector for fallback-enabled profiles."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = ""
    model: str = ""


class LanguageModelServiceSettings(BaseModel):
    """Resolved service settings defining chat and embedding model profiles."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    embedding: LanguageModelProfileSettings = LanguageModelProfileSettings(
        **DEFAULT_EMBEDDING_PROFILE
    )
    quick: LanguageModelProfileSettings
    standard: LanguageModelProfileSettings = LanguageModelProfileSettings(
        **DEFAULT_STANDARD_PROFILE
    )
    deep: LanguageModelProfileSettings


class _LanguageModelServiceSettingsInput(BaseModel):
    """Raw config shape supporting optional fallback-enabled reasoning levels."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    embedding: LanguageModelProfileSettings = LanguageModelProfileSettings(
        **DEFAULT_EMBEDDING_PROFILE
    )
    quick: LanguageModelOptionalProfileSettings = LanguageModelOptionalProfileSettings()
    standard: LanguageModelProfileSettings = LanguageModelProfileSettings(
        **DEFAULT_STANDARD_PROFILE
    )
    deep: LanguageModelOptionalProfileSettings = LanguageModelOptionalProfileSettings()


def resolve_language_model_service_settings(
    settings: BrainSettings,
) -> LanguageModelServiceSettings:
    """Resolve service settings from ``components.service.language_model``."""
    raw = resolve_component_settings(
        settings=settings,
        component_id=str(SERVICE_COMPONENT_ID),
        model=_LanguageModelServiceSettingsInput,
    )
    return LanguageModelServiceSettings(
        embedding=raw.embedding,
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
