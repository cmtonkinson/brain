"""Authoritative in-process Python API for Memory Authority Service."""

from __future__ import annotations

from abc import ABC, abstractmethod

from packages.brain_shared.config import CoreRuntimeSettings
from packages.brain_shared.envelope import Envelope, EnvelopeMeta
from services.action.language_model.service import LanguageModelService
from services.state.memory_authority.domain import (
    ContextBlock,
    FocusRecord,
    HealthStatus,
    SessionRecord,
)


class MemoryAuthorityService(ABC):
    """Public API for Memory Authority Service context and session operations."""

    @abstractmethod
    def assemble_context(
        self,
        *,
        meta: EnvelopeMeta,
        session_id: str,
        message: str,
    ) -> Envelope[ContextBlock]:
        """Append inbound message and return assembled Profile/Focus/Dialogue context."""

    @abstractmethod
    def record_response(
        self,
        *,
        meta: EnvelopeMeta,
        session_id: str,
        content: str,
        model: str,
        provider: str,
        token_count: int,
        reasoning_level: str,
    ) -> Envelope[bool]:
        """Append one outbound dialogue turn with response metadata."""

    @abstractmethod
    def update_focus(
        self,
        *,
        meta: EnvelopeMeta,
        session_id: str,
        content: str,
    ) -> Envelope[FocusRecord]:
        """Persist explicit focus content with budget-aware compaction semantics."""

    @abstractmethod
    def clear_session(
        self,
        *,
        meta: EnvelopeMeta,
        session_id: str,
    ) -> Envelope[bool]:
        """Advance dialogue pointer and clear focus without deleting historical data."""

    @abstractmethod
    def create_session(self, *, meta: EnvelopeMeta) -> Envelope[SessionRecord]:
        """Create and return one new MAS session."""

    @abstractmethod
    def get_session(
        self,
        *,
        meta: EnvelopeMeta,
        session_id: str,
    ) -> Envelope[SessionRecord]:
        """Read one MAS session by id."""

    @abstractmethod
    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        """Return MAS and Postgres substrate readiness."""


def build_memory_authority_service(
    *,
    settings: CoreRuntimeSettings,
    language_model: LanguageModelService,
) -> MemoryAuthorityService:
    """Build default Memory Authority implementation from typed settings."""
    from services.state.memory_authority.implementation import (
        DefaultMemoryAuthorityService,
    )

    return DefaultMemoryAuthorityService.from_settings(
        settings=settings,
        language_model=language_model,
    )
