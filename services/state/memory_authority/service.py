"""Authoritative in-process Python API for Memory Authority Service."""

from __future__ import annotations

from abc import ABC, abstractmethod

from lib.shared.config import CoreRuntimeSettings
from lib.shared.envelope import Envelope, EnvelopeMeta
from services.action.language_model.service import LanguageModelService
from services.state.memory_authority.domain import (
    ConversationalMemoryContext,
    ContextBlock,
    FocusRecord,
    HealthStatus,
    InboundInstructionRecord,
    SessionRecord,
    TurnContext,
    TurnRecord,
)


class MemoryAuthorityService(ABC):
    """Public API for Memory Authority Service context and session operations."""

    @abstractmethod
    def record_inbound_turn(
        self,
        *,
        meta: EnvelopeMeta,
        session_id: str,
        message: str,
        instruction: InboundInstructionRecord | None = None,
    ) -> Envelope[TurnRecord]:
        """Persist one inbound turn and return the recorded turn row."""

    @abstractmethod
    def assemble_snapshot(
        self,
        *,
        meta: EnvelopeMeta,
        session_id: str,
        exclude_latest: bool = True,
    ) -> Envelope[ContextBlock]:
        """Return the historical MAS context snapshot for one session.

        When *exclude_latest* is ``True`` (default, for Agent use), the most
        recent turn is excluded from the assembled context.  Pass ``False``
        to include all turns (e.g. for history display).
        """

    @abstractmethod
    def record_outbound_candidate(
        self,
        *,
        meta: EnvelopeMeta,
        session_id: str,
        content: str,
        model: str,
        provider: str,
        token_count: int,
        reasoning_level: str,
    ) -> Envelope[TurnRecord]:
        """Persist one outbound candidate turn and return the recorded row."""

    @abstractmethod
    def record_outbound_delivery(
        self,
        *,
        meta: EnvelopeMeta,
        session_id: str,
        turn_id: str,
        delivered: bool,
    ) -> Envelope[bool]:
        """Record delivery status for one outbound turn."""

    @abstractmethod
    def assemble_context(
        self,
        *,
        meta: EnvelopeMeta,
        session_id: str,
        message: str,
        instruction: InboundInstructionRecord | None = None,
    ) -> Envelope[TurnContext]:
        """Resolve the active session, record inbound turn, and assemble context."""

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
        """Backward-compatible wrapper for outbound candidate recording."""

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
    def compact_dialogue(
        self,
        *,
        meta: EnvelopeMeta,
        session_id: str,
    ) -> Envelope[SessionRecord]:
        """Force-summarize all visible turns and advance dialogue frontier to latest."""

    @abstractmethod
    def create_session(self, *, meta: EnvelopeMeta) -> Envelope[SessionRecord]:
        """Create and return one new MAS session."""

    @abstractmethod
    def get_latest_or_create_session(
        self, *, meta: EnvelopeMeta
    ) -> Envelope[SessionRecord]:
        """Return latest MAS session or create one when none exist."""

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


__all__ = [
    "ContextBlock",
    "ConversationalMemoryContext",
    "FocusRecord",
    "HealthStatus",
    "InboundInstructionRecord",
    "MemoryAuthorityService",
    "SessionRecord",
    "TurnContext",
    "TurnRecord",
    "build_memory_authority_service",
]
