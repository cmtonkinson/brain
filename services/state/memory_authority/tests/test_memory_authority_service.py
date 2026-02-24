"""Behavior tests for Memory Authority Service context and session semantics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from packages.brain_shared.envelope import EnvelopeKind, new_meta, success
from packages.brain_shared.ids import generate_ulid_str
from services.action.language_model.service import LanguageModelService
from services.state.memory_authority.config import MemoryAuthoritySettings
from services.state.memory_authority.domain import (
    BrainVerbosity,
    SessionRecord,
    TurnDirection,
    TurnRecord,
    TurnSummaryRecord,
    estimate_token_count,
)
from services.state.memory_authority.implementation import DefaultMemoryAuthorityService


@dataclass(frozen=True)
class _FakeRuntime:
    """Minimal runtime fake that only exposes health probe behavior."""

    healthy: bool = True

    def is_healthy(self) -> bool:
        """Return configured runtime health state."""
        return self.healthy


class _FakeMemoryRepository:
    """In-memory MAS repository fake for service behavior tests."""

    def __init__(self) -> None:
        self.sessions: dict[str, SessionRecord] = {}
        self.turns: dict[str, list[TurnRecord]] = {}
        self.summaries: dict[str, list[TurnSummaryRecord]] = {}

    def create_session(self) -> SessionRecord:
        """Create one session row."""
        now = _now()
        session = SessionRecord(
            id=generate_ulid_str(),
            focus=None,
            focus_token_count=None,
            dialogue_start_turn_id=None,
            created_at=now,
            updated_at=now,
        )
        self.sessions[session.id] = session
        self.turns[session.id] = []
        self.summaries[session.id] = []
        return session

    def get_session(self, *, session_id: str) -> SessionRecord | None:
        """Read one session by id."""
        return self.sessions.get(session_id)

    def update_focus(
        self,
        *,
        session_id: str,
        focus: str | None,
        focus_token_count: int | None,
    ) -> SessionRecord | None:
        """Update focus fields and return updated row."""
        session = self.sessions.get(session_id)
        if session is None:
            return None
        updated = session.model_copy(
            update={
                "focus": focus,
                "focus_token_count": focus_token_count,
                "updated_at": _now(),
            }
        )
        self.sessions[session_id] = updated
        return updated

    def clear_session(
        self,
        *,
        session_id: str,
        dialogue_start_turn_id: str | None,
    ) -> SessionRecord | None:
        """Clear focus and advance dialogue pointer."""
        session = self.sessions.get(session_id)
        if session is None:
            return None
        updated = session.model_copy(
            update={
                "focus": None,
                "focus_token_count": None,
                "dialogue_start_turn_id": dialogue_start_turn_id,
                "updated_at": _now(),
            }
        )
        self.sessions[session_id] = updated
        return updated

    def insert_turn(
        self,
        *,
        session_id: str,
        direction: TurnDirection,
        content: str,
        role: str,
        model: str | None,
        provider: str | None,
        token_count: int | None,
        reasoning_level: str | None,
        trace_id: str,
        principal: str,
    ) -> TurnRecord:
        """Insert one turn row for session."""
        record = TurnRecord(
            id=generate_ulid_str(),
            session_id=session_id,
            direction=direction,
            content=content,
            role=role,
            model=model,
            provider=provider,
            token_count=token_count,
            reasoning_level=reasoning_level,
            trace_id=trace_id,
            principal=principal,
            created_at=_now(),
        )
        self.turns.setdefault(session_id, []).append(record)
        return record

    def list_turns(self, *, session_id: str) -> list[TurnRecord]:
        """List turns for one session."""
        return list(self.turns.get(session_id, []))

    def get_latest_turn(self, *, session_id: str) -> TurnRecord | None:
        """Return latest turn for one session."""
        rows = self.turns.get(session_id, [])
        if not rows:
            return None
        return rows[-1]

    def list_turn_summaries(self, *, session_id: str) -> list[TurnSummaryRecord]:
        """List summary rows for one session."""
        return list(self.summaries.get(session_id, []))

    def get_turn_summary_by_range(
        self,
        *,
        session_id: str,
        start_turn_id: str,
        end_turn_id: str,
    ) -> TurnSummaryRecord | None:
        """Read one summary by exact turn range."""
        for summary in self.summaries.get(session_id, []):
            if (
                summary.start_turn_id == start_turn_id
                and summary.end_turn_id == end_turn_id
            ):
                return summary
        return None

    def create_turn_summary(
        self,
        *,
        session_id: str,
        start_turn_id: str,
        end_turn_id: str,
        content: str,
        token_count: int,
    ) -> TurnSummaryRecord:
        """Create one summary row idempotently."""
        existing = self.get_turn_summary_by_range(
            session_id=session_id,
            start_turn_id=start_turn_id,
            end_turn_id=end_turn_id,
        )
        if existing is not None:
            return existing
        record = TurnSummaryRecord(
            id=generate_ulid_str(),
            session_id=session_id,
            start_turn_id=start_turn_id,
            end_turn_id=end_turn_id,
            content=content,
            token_count=token_count,
            created_at=_now(),
        )
        self.summaries.setdefault(session_id, []).append(record)
        return record


class _FakeLanguageModelService(LanguageModelService):
    """LMS fake returning deterministic chat payloads for MAS tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.next_text: str = "compact summary"

    def chat(
        self,
        *,
        meta: object,
        prompt: str,
        profile: object = "standard",
    ) -> object:
        """Return deterministic chat response envelope."""
        del meta
        self.calls.append((prompt, str(profile)))
        return success(
            meta=_meta(),
            payload=_ChatPayload(text=self.next_text),
        )

    def chat_batch(
        self,
        *,
        meta: object,
        prompts: tuple[str, ...],
        profile: object = "standard",
    ) -> object:
        """Unused by MAS tests."""
        del meta, prompts, profile
        raise NotImplementedError

    def embed(
        self,
        *,
        meta: object,
        text: str,
        profile: object = "embedding",
    ) -> object:
        """Unused by MAS tests."""
        del meta, text, profile
        return success(
            meta=_meta(),
            payload=_EmbeddingPayload(values=(0.0,)),
        )

    def embed_batch(
        self,
        *,
        meta: object,
        texts: tuple[str, ...],
        profile: object = "embedding",
    ) -> object:
        """Unused by MAS tests."""
        del meta, texts, profile
        raise NotImplementedError

    def health(self, *, meta: object) -> object:
        """Unused by MAS tests."""
        del meta
        return success(
            meta=_meta(),
            payload=_HealthPayload(service_ready=True, adapter_ready=True, detail="ok"),
        )


@dataclass(frozen=True)
class _ChatPayload:
    """Minimal chat payload shape used by MAS LMS fakes."""

    text: str


@dataclass(frozen=True)
class _EmbeddingPayload:
    """Minimal embedding payload shape used by MAS LMS fakes."""

    values: tuple[float, ...]


@dataclass(frozen=True)
class _HealthPayload:
    """Minimal health payload shape used by MAS LMS fakes."""

    service_ready: bool
    adapter_ready: bool
    detail: str


def _now() -> datetime:
    """Return UTC timestamp for deterministic row construction."""
    return datetime.now(UTC)


def _meta() -> object:
    """Build valid command metadata for test requests."""
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def _build_service(
    *,
    dialogue_recent_turns: int = 10,
    dialogue_older_turns: int = 20,
    focus_token_budget: int = 512,
) -> tuple[
    DefaultMemoryAuthorityService, _FakeMemoryRepository, _FakeLanguageModelService
]:
    """Create MAS instance with in-memory repository and LMS fakes."""
    settings = MemoryAuthoritySettings(
        dialogue_recent_turns=dialogue_recent_turns,
        dialogue_older_turns=dialogue_older_turns,
        focus_token_budget=focus_token_budget,
        profile={
            "operator_name": "Operator",
            "brain_name": "Brain",
            "brain_verbosity": BrainVerbosity.NORMAL,
        },
    )
    repository = _FakeMemoryRepository()
    language_model = _FakeLanguageModelService()
    service = DefaultMemoryAuthorityService(
        settings=settings,
        runtime=_FakeRuntime(),
        language_model=language_model,
        repository=repository,
    )
    return service, repository, language_model


def test_session_create_clear_and_get() -> None:
    """MAS should create, clear, and read session state consistently."""
    service, repository, _ = _build_service()

    created = service.create_session(meta=_meta())
    assert created.ok
    assert created.payload is not None
    session_id = created.payload.value.id

    _ = service.update_focus(meta=_meta(), session_id=session_id, content="active work")
    _ = service.assemble_context(meta=_meta(), session_id=session_id, message="hello")

    cleared = service.clear_session(meta=_meta(), session_id=session_id)
    assert cleared.ok
    assert cleared.payload is not None
    assert cleared.payload.value is True

    fetched = service.get_session(meta=_meta(), session_id=session_id)
    assert fetched.ok
    assert fetched.payload is not None
    assert fetched.payload.value.focus is None
    assert fetched.payload.value.focus_token_count is None
    assert (
        fetched.payload.value.dialogue_start_turn_id
        == repository.turns[session_id][-1].id
    )


def test_assemble_context_returns_expected_shape() -> None:
    """Assembled context should include profile, focus, dialogue, and empty references."""
    service, _, _ = _build_service()
    created = service.create_session(meta=_meta())
    assert created.payload is not None
    session_id = created.payload.value.id

    _ = service.update_focus(meta=_meta(), session_id=session_id, content="focus state")
    result = service.assemble_context(meta=_meta(), session_id=session_id, message="hi")

    assert result.ok
    assert result.payload is not None
    block = result.payload.value
    assert block.profile.operator_name == "Operator"
    assert block.profile.brain_name == "Brain"
    assert block.profile.brain_verbosity == BrainVerbosity.NORMAL
    assert block.focus == "focus state"
    assert len(block.dialogue) == 1
    assert block.dialogue[0].role == "user"
    assert block.dialogue[0].content == "hi"
    assert block.reference_snippets == []


def test_dialogue_respects_recent_and_older_boundaries() -> None:
    """Dialogue assembly should keep recent verbatim turns and cap older coverage."""
    service, _, _ = _build_service(dialogue_recent_turns=2, dialogue_older_turns=3)
    created = service.create_session(meta=_meta())
    assert created.payload is not None
    session_id = created.payload.value.id

    for idx in range(5):
        _ = service.record_response(
            meta=_meta(),
            session_id=session_id,
            content=f"assistant-{idx}",
            model="test",
            provider="unit",
            token_count=3,
            reasoning_level="standard",
        )

    context = service.assemble_context(
        meta=_meta(),
        session_id=session_id,
        message="latest-user",
    )
    assert context.ok
    assert context.payload is not None

    dialogue = context.payload.value.dialogue
    assert len(dialogue) >= 3
    assert dialogue[-1].content == "latest-user"
    assert dialogue[-1].is_summary is False
    assert any(item.is_summary for item in dialogue[:-2])


def test_focus_compaction_triggers_when_budget_exceeded() -> None:
    """Focus updates above budget should invoke LMS quick compaction."""
    service, _, language_model = _build_service(focus_token_budget=4)
    created = service.create_session(meta=_meta())
    assert created.payload is not None
    session_id = created.payload.value.id

    language_model.next_text = "short focus"
    long_text = "one two three four five six seven"
    result = service.update_focus(
        meta=_meta(), session_id=session_id, content=long_text
    )

    assert result.ok
    assert result.payload is not None
    assert result.payload.value.content == "short focus"
    assert result.payload.value.token_count == estimate_token_count("short focus")
    assert any(profile == "quick" for _, profile in language_model.calls)


def test_record_response_persists_turn_metadata() -> None:
    """record_response should persist outbound turn metadata exactly."""
    service, repository, _ = _build_service()
    created = service.create_session(meta=_meta())
    assert created.payload is not None
    session_id = created.payload.value.id

    result = service.record_response(
        meta=_meta(),
        session_id=session_id,
        content="assistant response",
        model="gpt-test",
        provider="unit",
        token_count=42,
        reasoning_level="deep",
    )
    assert result.ok

    turns = repository.turns[session_id]
    assert len(turns) == 1
    turn = turns[0]
    assert turn.direction == TurnDirection.OUTBOUND
    assert turn.content == "assistant response"
    assert turn.model == "gpt-test"
    assert turn.provider == "unit"
    assert turn.token_count == 42
    assert turn.reasoning_level == "deep"


def test_turn_summary_range_uses_distinct_endpoints_for_multi_turn_summary() -> None:
    """Multi-turn summary ranges should persist distinct start/end turn ids."""
    service, repository, _ = _build_service(
        dialogue_recent_turns=1, dialogue_older_turns=10
    )
    created = service.create_session(meta=_meta())
    assert created.payload is not None
    session_id = created.payload.value.id

    for idx in range(4):
        _ = service.record_response(
            meta=_meta(),
            session_id=session_id,
            content=f"assistant-{idx}",
            model="test",
            provider="unit",
            token_count=2,
            reasoning_level="quick",
        )

    assembled = service.assemble_context(
        meta=_meta(), session_id=session_id, message="user-final"
    )
    assert assembled.ok

    summaries = repository.summaries[session_id]
    assert summaries
    first = summaries[0]
    assert first.start_turn_id != first.end_turn_id
