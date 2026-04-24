"""Behavior tests for Recall Service context and session semantics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from lib.shared.envelope import EnvelopeKind, new_meta, success
from lib.shared.ids import generate_ulid_str
from services.effect.language.service import LanguageService
from services.reason.recall.config import RecallSettings
from services.reason.recall.domain import (
    InboundInstructionRecord,
    SessionRecord,
    TurnDirection,
    TurnRecord,
    estimate_token_count,
)
from services.reason.recall.implementation import DefaultRecallService


@dataclass(frozen=True)
class _FakeRuntime:
    """Minimal runtime fake that only exposes health probe behavior."""

    healthy: bool = True

    def is_healthy(self) -> bool:
        """Return configured runtime health state."""
        return self.healthy


class _FakeMemoryRepository:
    """In-memory Recall repository fake for service behavior tests."""

    def __init__(self) -> None:
        self.sessions: dict[str, SessionRecord] = {}
        self.turns: dict[str, list[TurnRecord]] = {}

    def create_session(self) -> SessionRecord:
        """Create one session row."""
        now = _now()
        session = SessionRecord(
            id=generate_ulid_str(),
            focus=None,
            focus_token_count=None,
            dialogue_summary=None,
            dialogue_summary_token_count=None,
            dialogue_start_turn_id=None,
            current_conversation_episode_id=generate_ulid_str(),
            last_episode_inbound_at=None,
            created_at=now,
            updated_at=now,
        )
        self.sessions[session.id] = session
        self.turns[session.id] = []
        return session

    def get_latest_session(self) -> SessionRecord | None:
        """Return the most recently updated session row when present."""
        if not self.sessions:
            return None
        return max(self.sessions.values(), key=lambda item: (item.updated_at, item.id))

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
                "dialogue_summary": None,
                "dialogue_summary_token_count": None,
                "dialogue_start_turn_id": dialogue_start_turn_id,
                "updated_at": _now(),
            }
        )
        self.sessions[session_id] = updated
        return updated

    def update_dialogue_summary(
        self,
        *,
        session_id: str,
        dialogue_summary: str | None,
        dialogue_summary_token_count: int | None,
        dialogue_start_turn_id: str | None,
    ) -> SessionRecord | None:
        """Update rolling summary state and checkpoint."""
        session = self.sessions.get(session_id)
        if session is None:
            return None
        updated = session.model_copy(
            update={
                "dialogue_summary": dialogue_summary,
                "dialogue_summary_token_count": dialogue_summary_token_count,
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
        conversation_episode_id: str,
        principal: str,
        source: str | None = None,
        instruction: InboundInstructionRecord | None = None,
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
            conversation_episode_id=conversation_episode_id,
            principal=principal,
            source=source,
            sender_e164=None if instruction is None else instruction.sender_e164,
            timestamp_ms=None if instruction is None else instruction.timestamp_ms,
            source_device=None if instruction is None else instruction.source_device,
            group_id=None if instruction is None else instruction.group_id,
            quote_target_timestamp_ms=(
                None if instruction is None else instruction.quote_target_timestamp_ms
            ),
            reaction_target_timestamp_ms=(
                None
                if instruction is None
                else instruction.reaction_target_timestamp_ms
            ),
            reaction_emoji=None if instruction is None else instruction.reaction_emoji,
            approval_intent=(
                None if instruction is None else instruction.approval_intent
            ),
            reply_to_proposal_token=(
                None if instruction is None else instruction.reply_to_proposal_token
            ),
            reaction_to_proposal_token=(
                None if instruction is None else instruction.reaction_to_proposal_token
            ),
            created_at=_now(),
        )
        self.turns.setdefault(session_id, []).append(record)
        return record

    def resolve_conversation_episode(
        self,
        *,
        session_id: str,
        inbound_at: datetime,
        idle_seconds: int,
    ) -> str | None:
        """Return or create one in-memory conversation episode id."""
        session = self.sessions.get(session_id)
        if session is None:
            return None
        rotate = session.current_conversation_episode_id is None
        if not rotate and session.last_episode_inbound_at is not None:
            rotate = (
                inbound_at - session.last_episode_inbound_at
            ).total_seconds() > idle_seconds
        episode_id = (
            generate_ulid_str() if rotate else session.current_conversation_episode_id
        )
        self.sessions[session_id] = session.model_copy(
            update={
                "current_conversation_episode_id": episode_id,
                "last_episode_inbound_at": inbound_at,
            }
        )
        return episode_id

    def list_turns(self, *, session_id: str) -> list[TurnRecord]:
        """List turns for one session."""
        return list(self.turns.get(session_id, []))

    def get_latest_turn(self, *, session_id: str) -> TurnRecord | None:
        """Return latest turn for one session."""
        rows = self.turns.get(session_id, [])
        if not rows:
            return None
        return rows[-1]


class _FakeLanguageService(LanguageService):
    """Language fake returning deterministic chat payloads for Recall tests."""

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
        """Unused by Recall tests."""
        del meta, prompts, profile
        raise NotImplementedError

    def chat_with_tools(
        self,
        *,
        meta: object,
        messages,
        tools=(),
        tool_choice=None,
        parallel_tool_calls=None,
        allow_text_output: bool = True,
        profile: object = "standard",
    ) -> object:
        """Unused by Recall tests."""
        del (
            meta,
            messages,
            tools,
            tool_choice,
            parallel_tool_calls,
            allow_text_output,
            profile,
        )
        raise NotImplementedError

    def embed(
        self,
        *,
        meta: object,
        text: str,
        profile: object = "embedding",
    ) -> object:
        """Unused by Recall tests."""
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
        """Unused by Recall tests."""
        del meta, texts, profile
        raise NotImplementedError

    def get_token_usage_by_trace(self, *, meta: object, trace_id: str) -> object:
        """Unused by Recall tests."""
        del meta, trace_id
        raise NotImplementedError

    def health(self, *, meta: object) -> object:
        """Unused by Recall tests."""
        del meta
        return success(
            meta=_meta(),
            payload=_HealthPayload(service_ready=True, adapter_ready=True, detail="ok"),
        )


@dataclass(frozen=True)
class _ChatPayload:
    """Minimal chat payload shape used by Recall Language fakes."""

    text: str


@dataclass(frozen=True)
class _EmbeddingPayload:
    """Minimal embedding payload shape used by Recall Language fakes."""

    values: tuple[float, ...]


@dataclass(frozen=True)
class _HealthPayload:
    """Minimal health payload shape used by Recall Language fakes."""

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
    min_turns_to_keep: int = 10,
    max_turns_to_keep: int = 20,
    focus_token_budget: int = 512,
    conversation_episode_idle_seconds: int = 3600,
) -> tuple[DefaultRecallService, _FakeMemoryRepository, _FakeLanguageService]:
    """Create Recall instance with in-memory repository and Language fakes."""
    settings = RecallSettings(
        min_turns_to_keep=min_turns_to_keep,
        max_turns_to_keep=max_turns_to_keep,
        focus_token_budget=focus_token_budget,
        conversation_episode_idle_seconds=conversation_episode_idle_seconds,
    )
    repository = _FakeMemoryRepository()
    language_model = _FakeLanguageService()
    service = DefaultRecallService(
        settings=settings,
        runtime=_FakeRuntime(),
        language_model=language_model,
        repository=repository,
    )
    return service, repository, language_model


def test_session_create_clear_and_get() -> None:
    """Recall should create, clear, and read session state consistently."""
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


def test_create_session_mints_initial_conversation_episode() -> None:
    """New Recall sessions should start a new conversation episode."""
    service, _repository, _ = _build_service()

    created = service.create_session(meta=_meta())

    assert created.ok
    assert created.payload is not None
    assert created.payload.value.current_conversation_episode_id not in (None, "")
    assert created.payload.value.last_episode_inbound_at is None


def test_assemble_context_returns_expected_shape() -> None:
    """Assembled context should return the historical snapshot before the new turn."""
    service, repository, _ = _build_service()
    created = service.create_session(meta=_meta())
    assert created.payload is not None
    session_id = created.payload.value.id

    _ = service.update_focus(meta=_meta(), session_id=session_id, content="focus state")
    _ = service.record_response(
        meta=_meta(),
        session_id=session_id,
        content="prior assistant",
        model="test",
        provider="unit",
        token_count=3,
        reasoning_level="standard",
    )
    result = service.assemble_context(meta=_meta(), session_id=session_id, message="hi")

    assert result.ok
    assert result.payload is not None
    block = result.payload.value.context
    assert block.current_focus == "focus state"
    assert block.recent_conversation_summary == ""
    assert [turn.content for turn in block.recent_turns] == ["prior assistant"]
    assert block.reference_snippets == []
    assert repository.turns[session_id][-1].content == "hi"


def test_get_latest_or_create_session_prefers_existing_session() -> None:
    """Recall should return the newest existing session before creating another."""
    service, repository, _ = _build_service()
    first = repository.create_session()
    second = repository.create_session()
    repository.update_focus(
        session_id=second.id,
        focus="active",
        focus_token_count=1,
    )

    result = service.get_latest_or_create_session(meta=_meta())

    assert result.ok
    assert result.payload is not None
    assert result.payload.value.id == second.id
    assert set(repository.sessions) == {first.id, second.id}


def test_get_latest_or_create_session_creates_when_empty() -> None:
    """Recall should create one session when none exist yet."""
    service, repository, _ = _build_service()

    result = service.get_latest_or_create_session(meta=_meta())

    assert result.ok
    assert result.payload is not None
    assert result.payload.value.id in repository.sessions
    assert len(repository.sessions) == 1


def test_dialogue_respects_recent_and_older_boundaries() -> None:
    """Dialogue assembly should roll older turns into session summary at threshold."""
    service, repository, _ = _build_service(min_turns_to_keep=2, max_turns_to_keep=3)
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

    recent_turns = context.payload.value.context.recent_turns
    assert len(recent_turns) == 2
    assert recent_turns[-1].content == "assistant-4"
    assert recent_turns[-1].is_summary is False
    assert all(item.content != "latest-user" for item in recent_turns)
    assert context.payload.value.context.recent_conversation_summary != ""
    assert repository.sessions[session_id].dialogue_start_turn_id is not None
    assert repository.sessions[session_id].dialogue_summary is not None


def test_focus_compaction_triggers_when_budget_exceeded() -> None:
    """Focus updates above budget should invoke Language quick compaction."""
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


def test_record_inbound_turn_persists_turn_metadata() -> None:
    """record_inbound_turn should persist inbound turn metadata exactly."""
    service, repository, _ = _build_service()
    created = service.create_session(meta=_meta())
    assert created.payload is not None
    session_id = created.payload.value.id

    result = service.record_inbound_turn(
        meta=_meta(),
        session_id=session_id,
        message="operator instruction",
    )
    assert result.ok
    assert result.payload is not None
    turn = result.payload.value
    assert turn.direction == TurnDirection.INBOUND
    assert turn.content == "operator instruction"

    turns = repository.turns[session_id]
    assert len(turns) == 1
    assert turns[0].id == turn.id


def test_record_inbound_turn_rotates_conversation_episode_after_idle_gap() -> None:
    """Inbound turns should reuse or rotate Recall-owned conversation episodes by idle gap."""
    service, _repository, _ = _build_service(conversation_episode_idle_seconds=60)
    created = service.create_session(meta=_meta())
    assert created.payload is not None
    session_id = created.payload.value.id
    initial_episode_id = created.payload.value.current_conversation_episode_id

    first = service.record_inbound_turn(
        meta=_meta(),
        session_id=session_id,
        message="first",
        instruction=InboundInstructionRecord(
            sender_e164="+12025550100",
            message_text="first",
            timestamp_ms=1_710_000_000_000,
            source_device="1",
            source="signal",
        ),
    )
    second = service.record_inbound_turn(
        meta=_meta(),
        session_id=session_id,
        message="second",
        instruction=InboundInstructionRecord(
            sender_e164="+12025550100",
            message_text="second",
            timestamp_ms=1_710_000_030_000,
            source_device="1",
            source="signal",
        ),
    )
    third = service.record_inbound_turn(
        meta=_meta(),
        session_id=session_id,
        message="third",
        instruction=InboundInstructionRecord(
            sender_e164="+12025550100",
            message_text="third",
            timestamp_ms=1_710_000_120_001,
            source_device="1",
            source="signal",
        ),
    )

    assert first.payload is not None
    assert second.payload is not None
    assert third.payload is not None
    assert first.payload.value.conversation_episode_id == initial_episode_id
    assert second.payload.value.conversation_episode_id == (
        first.payload.value.conversation_episode_id
    )
    assert third.payload.value.conversation_episode_id != (
        first.payload.value.conversation_episode_id
    )


def test_assemble_snapshot_excludes_current_live_turn() -> None:
    """assemble_snapshot should omit the current live inbound turn from dialogue."""
    service, _, _ = _build_service()
    created = service.create_session(meta=_meta())
    assert created.payload is not None
    session_id = created.payload.value.id

    _ = service.record_response(
        meta=_meta(),
        session_id=session_id,
        content="prior assistant",
        model="test",
        provider="unit",
        token_count=3,
        reasoning_level="standard",
    )
    _ = service.record_inbound_turn(
        meta=_meta(),
        session_id=session_id,
        message="live instruction",
    )

    snapshot = service.assemble_snapshot(meta=_meta(), session_id=session_id)
    assert snapshot.ok
    assert snapshot.payload is not None
    assert snapshot.payload.value.recent_conversation_summary == ""
    assert [turn.content for turn in snapshot.payload.value.recent_turns] == [
        "prior assistant"
    ]


def test_summary_rolls_forward_without_dropping_older_history() -> None:
    """Rolling summary should absorb older turns and retain newest minimum verbatim."""
    service, repository, _ = _build_service(min_turns_to_keep=1, max_turns_to_keep=2)
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

    session = repository.sessions[session_id]
    assert session.dialogue_summary is not None
    assert session.dialogue_start_turn_id is not None
    assert [turn.content for turn in assembled.payload.value.context.recent_turns] == [
        "assistant-3"
    ]


def test_compact_dialogue_absorbs_all_visible_turns() -> None:
    """compact_dialogue should fold all visible turns into summary and zero out recent turns."""
    service, repository, language_model = _build_service(
        min_turns_to_keep=2, max_turns_to_keep=20
    )
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

    language_model.next_text = "compacted summary of five turns"
    result = service.compact_dialogue(meta=_meta(), session_id=session_id)

    assert result.ok
    assert result.payload is not None
    session = result.payload.value
    assert session.dialogue_summary == "compacted summary of five turns"
    assert session.dialogue_start_turn_id == repository.turns[session_id][-1].id

    # Next snapshot should have zero recent turns.
    snapshot = service.assemble_snapshot(
        meta=_meta(), session_id=session_id, exclude_latest=False
    )
    assert snapshot.ok
    assert snapshot.payload is not None
    assert snapshot.payload.value.recent_turns == []
    assert snapshot.payload.value.recent_conversation_summary != ""


def test_compact_dialogue_noop_when_no_visible_turns() -> None:
    """compact_dialogue should be a no-op when no visible turns exist."""
    service, _repository, language_model = _build_service()
    created = service.create_session(meta=_meta())
    assert created.payload is not None
    session_id = created.payload.value.id

    calls_before = len(language_model.calls)
    result = service.compact_dialogue(meta=_meta(), session_id=session_id)

    assert result.ok
    assert result.payload is not None
    assert result.payload.value.dialogue_summary is None
    assert result.payload.value.dialogue_start_turn_id is None
    assert len(language_model.calls) == calls_before


def test_compact_dialogue_with_existing_summary() -> None:
    """compact_dialogue should fold new turns into an existing rolling summary."""
    service, repository, language_model = _build_service(
        min_turns_to_keep=2, max_turns_to_keep=4
    )
    created = service.create_session(meta=_meta())
    assert created.payload is not None
    session_id = created.payload.value.id

    # Generate enough turns to trigger auto-compaction.
    language_model.next_text = "auto summary"
    for idx in range(6):
        _ = service.record_response(
            meta=_meta(),
            session_id=session_id,
            content=f"assistant-{idx}",
            model="test",
            provider="unit",
            token_count=3,
            reasoning_level="standard",
        )
    # Trigger auto-compaction via assemble.
    _ = service.assemble_context(meta=_meta(), session_id=session_id, message="trigger")
    session_before = repository.sessions[session_id]
    assert session_before.dialogue_summary is not None

    # Add more turns after auto-compaction.
    for idx in range(3):
        _ = service.record_response(
            meta=_meta(),
            session_id=session_id,
            content=f"post-compact-{idx}",
            model="test",
            provider="unit",
            token_count=3,
            reasoning_level="standard",
        )

    # Now force compact — should fold remaining visible turns into existing summary.
    language_model.next_text = "fully compacted summary"
    result = service.compact_dialogue(meta=_meta(), session_id=session_id)

    assert result.ok
    assert result.payload is not None
    assert result.payload.value.dialogue_summary == "fully compacted summary"
    assert (
        result.payload.value.dialogue_start_turn_id
        == repository.turns[session_id][-1].id
    )

    # Verify zero recent turns after compact.
    snapshot = service.assemble_snapshot(
        meta=_meta(), session_id=session_id, exclude_latest=False
    )
    assert snapshot.ok
    assert snapshot.payload.value.recent_turns == []


def test_compact_dialogue_session_not_found() -> None:
    """compact_dialogue should return not-found for non-existent session."""
    service, _, _ = _build_service()

    result = service.compact_dialogue(
        meta=_meta(), session_id="01JAAAAAAAAAAAAAAAAAAAAAAAA"
    )

    assert not result.ok
    assert len(result.errors) > 0


def test_compact_dialogue_preserves_focus() -> None:
    """compact_dialogue should leave focus state unchanged."""
    service, repository, language_model = _build_service()
    created = service.create_session(meta=_meta())
    assert created.payload is not None
    session_id = created.payload.value.id

    _ = service.update_focus(
        meta=_meta(), session_id=session_id, content="important focus"
    )
    for idx in range(3):
        _ = service.record_response(
            meta=_meta(),
            session_id=session_id,
            content=f"assistant-{idx}",
            model="test",
            provider="unit",
            token_count=3,
            reasoning_level="standard",
        )

    language_model.next_text = "compact result"
    result = service.compact_dialogue(meta=_meta(), session_id=session_id)

    assert result.ok
    session = repository.sessions[session_id]
    assert session.focus == "important focus"
    assert session.dialogue_summary == "compact result"


def test_health_reports_ready_when_runtime_healthy() -> None:
    """Health should report service and substrate ready when runtime is healthy."""
    service, _, _ = _build_service()

    result = service.health(meta=_meta())

    assert result.ok
    assert result.payload is not None
    assert result.payload.value.service_ready is True
    assert result.payload.value.substrate_ready is True


def test_health_degrades_when_runtime_unhealthy() -> None:
    """Health should report degraded substrate when Postgres ping fails."""
    settings = RecallSettings()
    repository = _FakeMemoryRepository()
    language_model = _FakeLanguageService()
    service = DefaultRecallService(
        settings=settings,
        runtime=_FakeRuntime(healthy=False),
        language_model=language_model,
        repository=repository,
    )

    result = service.health(meta=_meta())

    assert result.ok
    assert result.payload is not None
    assert result.payload.value.substrate_ready is False


def test_get_session_returns_not_found_for_missing_session() -> None:
    """get_session should return not-found error for non-existent session id."""
    service, _, _ = _build_service()

    result = service.get_session(meta=_meta(), session_id=generate_ulid_str())

    assert not result.ok
    assert result.errors[0].category.value == "not_found"


def test_record_outbound_candidate_persists_turn_and_metadata() -> None:
    """record_outbound_candidate should persist one outbound turn with metadata."""
    service, repository, _ = _build_service()
    created = service.create_session(meta=_meta())
    assert created.payload is not None
    session_id = created.payload.value.id

    result = service.record_outbound_candidate(
        meta=_meta(),
        session_id=session_id,
        content="candidate reply",
        model="test-model",
        provider="test-provider",
        token_count=10,
        reasoning_level="standard",
    )

    assert result.ok
    assert result.payload is not None
    turn = result.payload.value
    assert turn.direction == TurnDirection.OUTBOUND
    assert turn.content == "candidate reply"
    assert turn.model == "test-model"
    assert turn.provider == "test-provider"


def test_record_inbound_rejects_invalid_session_id() -> None:
    """Malformed session ids should produce validation errors."""
    service, _, _ = _build_service()

    result = service.record_inbound_turn(
        meta=_meta(), session_id="not-a-ulid", message="hello"
    )

    assert not result.ok
    assert result.errors[0].category.value == "validation"


def test_record_outbound_delivery_rejects_invalid_turn_id() -> None:
    """Malformed turn ids should produce validation errors."""
    service, _, _ = _build_service()
    created = service.create_session(meta=_meta())
    assert created.payload is not None

    result = service.record_outbound_delivery(
        meta=_meta(),
        session_id=created.payload.value.id,
        turn_id="not-a-ulid",
        delivered=True,
    )

    assert not result.ok
    assert result.errors[0].category.value == "validation"
