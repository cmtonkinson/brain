"""Memory Authority Service native package exports."""

from packages.brain_shared.envelope import Envelope, EnvelopeKind, EnvelopeMeta
from packages.brain_shared.errors import ErrorCategory, ErrorDetail
from services.state.memory_authority.component import MANIFEST
from services.state.memory_authority.config import MemoryAuthoritySettings
from services.state.memory_authority.domain import (
    BrainVerbosity,
    ContextBlock,
    DialogueTurn,
    FocusRecord,
    HealthStatus,
    ProfileContext,
    SessionRecord,
)
from services.state.memory_authority.implementation import DefaultMemoryAuthorityService
from services.state.memory_authority.service import MemoryAuthorityService

__all__ = [
    "MANIFEST",
    "MemoryAuthorityService",
    "MemoryAuthoritySettings",
    "DefaultMemoryAuthorityService",
    "BrainVerbosity",
    "ProfileContext",
    "DialogueTurn",
    "ContextBlock",
    "FocusRecord",
    "SessionRecord",
    "HealthStatus",
    "Envelope",
    "EnvelopeKind",
    "EnvelopeMeta",
    "ErrorCategory",
    "ErrorDetail",
]
