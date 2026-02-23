"""Pydantic settings for the Language Model Service."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from packages.brain_shared.config import BrainSettings, resolve_component_settings
from services.action.language_model.component import SERVICE_COMPONENT_ID


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
    """Service settings defining chat and embedding model profiles."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    embedding: LanguageModelProfileSettings = LanguageModelProfileSettings(
        provider="ollama",
        model="mxbai-embed-large",
    )
    chat_default: LanguageModelProfileSettings = LanguageModelProfileSettings(
        provider="ollama",
        model="gpt-oss",
    )
    chat_advanced: LanguageModelOptionalProfileSettings = (
        LanguageModelOptionalProfileSettings()
    )


def resolve_language_model_service_settings(
    settings: BrainSettings,
) -> LanguageModelServiceSettings:
    """Resolve service settings from ``components.service_language_model``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(SERVICE_COMPONENT_ID),
        model=LanguageModelServiceSettings,
    )
