"""Cross-service orchestration tests for Recall->Language behavior."""

from __future__ import annotations

from lib.shared.envelope import EnvelopeKind, new_meta
from services.reason.recall.config import RecallSettings
from services.reason.recall.implementation import DefaultRecallService
from services.reason.recall.tests.test_recall_service import (
    _FakeLanguageService,
    _FakeMemoryRepository,
    _FakeRuntime,
)


def _meta():
    """Build deterministic metadata envelope for Recall calls."""
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def test_update_focus_routes_through_language_model_dependency() -> None:
    """Recall update_focus should execute using the injected Language service dependency."""
    language_model = _FakeLanguageService()
    service = DefaultRecallService(
        settings=RecallSettings(),
        runtime=_FakeRuntime(),
        language_model=language_model,
        repository=_FakeMemoryRepository(),
    )
    session_id = service.create_session(meta=_meta()).payload.value.id

    updated = service.update_focus(meta=_meta(), session_id=session_id, content="focus")

    assert updated.ok is True
