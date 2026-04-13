"""Integration-style Memory Authority tests for LMS/repository interaction."""

from __future__ import annotations

from packages.brain_shared.envelope import EnvelopeKind, new_meta
from services.state.memory_authority.config import MemoryAuthoritySettings
from services.state.memory_authority.implementation import DefaultMemoryAuthorityService
from services.state.memory_authority.tests.test_memory_authority_service import (
    _FakeLanguageModelService,
    _FakeMemoryRepository,
    _FakeRuntime,
)


def _meta():
    """Build deterministic envelope metadata."""
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def test_session_context_record_and_clear_flow() -> None:
    """Service should support end-to-end session lifecycle flow."""
    service = DefaultMemoryAuthorityService(
        settings=MemoryAuthoritySettings(),
        runtime=_FakeRuntime(),
        language_model=_FakeLanguageModelService(),
        repository=_FakeMemoryRepository(),
    )

    created = service.create_session(meta=_meta())
    assert created.ok is True
    session_id = created.payload.value.id

    assembled = service.assemble_context(
        meta=_meta(), session_id=session_id, message="hi"
    )
    assert assembled.ok is True

    recorded = service.record_response(
        meta=_meta(),
        session_id=session_id,
        content="hello",
        model="gpt-oss",
        provider="ollama",
        token_count=3,
        reasoning_level="standard",
    )
    assert recorded.ok is True

    cleared = service.clear_session(meta=_meta(), session_id=session_id)
    assert cleared.ok is True
