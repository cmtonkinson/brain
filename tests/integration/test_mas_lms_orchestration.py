"""Cross-service orchestration tests for MAS->LMS behavior."""

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
    """Build deterministic metadata envelope for MAS calls."""
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def test_update_focus_routes_through_language_model_dependency() -> None:
    """MAS update_focus should execute using the injected LMS service dependency."""
    language_model = _FakeLanguageModelService()
    service = DefaultMemoryAuthorityService(
        settings=MemoryAuthoritySettings(),
        runtime=_FakeRuntime(),
        language_model=language_model,
        repository=_FakeMemoryRepository(),
    )
    session_id = service.create_session(meta=_meta()).payload.value.id

    updated = service.update_focus(meta=_meta(), session_id=session_id, content="focus")

    assert updated.ok is True
