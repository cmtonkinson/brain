"""Language Model Service package exports."""

from packages.brain_shared.envelope import Envelope, EnvelopeKind, EnvelopeMeta
from packages.brain_shared.errors import ErrorCategory, ErrorDetail
from services.action.language_model.component import MANIFEST
from services.action.language_model.config import (
    LanguageModelOptionalProfileSettings,
    LanguageModelProfileSettings,
    LanguageModelServiceSettings,
    resolve_language_model_service_settings,
)
from services.action.language_model.domain import (
    ChatMessage,
    ChatResponse,
    ChatToolCall,
    ChatToolDefinition,
    ChatWithToolsResponse,
    EmbeddingVector,
    HealthStatus,
)
from services.action.language_model.implementation import DefaultLanguageModelService
from services.action.language_model.service import LanguageModelService
from services.action.language_model.validation import EmbeddingProfile, ReasoningLevel

__all__ = [
    "ChatResponse",
    "ChatMessage",
    "ChatToolCall",
    "ChatToolDefinition",
    "ChatWithToolsResponse",
    "DefaultLanguageModelService",
    "EmbeddingVector",
    "Envelope",
    "EnvelopeKind",
    "EnvelopeMeta",
    "ErrorCategory",
    "ErrorDetail",
    "HealthStatus",
    "EmbeddingProfile",
    "LanguageModelOptionalProfileSettings",
    "LanguageModelProfileSettings",
    "LanguageModelService",
    "LanguageModelServiceSettings",
    "MANIFEST",
    "ReasoningLevel",
    "resolve_language_model_service_settings",
]
