"""HTTP route adapter tests for Memory Authority Service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, UTC

from fastapi import APIRouter
from fastapi.testclient import TestClient

from lib.shared.envelope import EnvelopeKind, failure, new_meta, success
from lib.shared.errors import validation_error
from lib.shared.http.server import create_app
from services.state.memory_authority.api import register_routes
from services.state.memory_authority.domain import (
    ContextBlock,
    DialogueTurn,
    InboundInstructionRecord,
    SessionRecord,
    TurnContext,
    TurnDirection,
    TurnRecord,
)
from services.state.memory_authority.service import MemoryAuthorityService


@dataclass(frozen=True)
class _AssembleCall:
    """Captured assemble-context invocation arguments."""

    session_id: str
    message: str
    source: str
    principal: str


@dataclass(frozen=True)
class _RecordResponseCall:
    """Captured record-response invocation arguments."""

    session_id: str
    content: str
    model: str
    provider: str
    token_count: int
    reasoning_level: str
    source: str
    principal: str


@dataclass(frozen=True)
class _TurnCall:
    """Captured turn-record invocation arguments."""

    session_id: str
    message: str
    source: str
    principal: str


@dataclass(frozen=True)
class _CandidateCall:
    """Captured outbound-candidate invocation arguments."""

    session_id: str
    content: str
    model: str
    provider: str
    token_count: int
    reasoning_level: str
    source: str
    principal: str


@dataclass(frozen=True)
class _DeliveryCall:
    """Captured outbound-delivery invocation arguments."""

    session_id: str
    turn_id: str
    delivered: bool
    source: str
    principal: str


class _FakeMemoryAuthorityService(MemoryAuthorityService):
    """Programmable MAS fake for route-adapter tests."""

    def __init__(self) -> None:
        self.record_inbound_calls: list[_TurnCall] = []
        self.assemble_snapshot_calls: list[tuple[str, str]] = []
        self.record_outbound_candidate_calls: list[_CandidateCall] = []
        self.record_outbound_delivery_calls: list[_DeliveryCall] = []
        self.assemble_calls: list[_AssembleCall] = []
        self.record_response_calls: list[_RecordResponseCall] = []
        self.create_session_calls: list[tuple[str, str]] = []
        self.get_latest_or_create_session_calls: list[tuple[str, str]] = []
        self.record_inbound_result = success(
            meta=_meta(),
            payload=TurnRecord(
                id="turn-inbound",
                session_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
                direction=TurnDirection.INBOUND,
                content="hello",
                role="user",
                model=None,
                provider=None,
                token_count=3,
                reasoning_level=None,
                trace_id="trace",
                conversation_episode_id="episode",
                principal="operator",
                created_at=datetime.now(UTC),
            ),
        )
        self.assemble_result = success(
            meta=_meta(),
            payload=ContextBlock(
                current_focus="current focus",
                recent_conversation_summary="prior summary",
                recent_turns=[
                    DialogueTurn(role="user", content="hello", is_summary=False)
                ],
                reference_snippets=[],
            ),
        )
        self.turn_context_result = success(
            meta=_meta(),
            payload=TurnContext(
                session_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
                inbound_turn=self.record_inbound_result.payload.value,
                context=self.assemble_result.payload.value,
            ),
        )
        self.record_outbound_candidate_result = success(
            meta=_meta(),
            payload=TurnRecord(
                id="turn-outbound",
                session_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
                direction=TurnDirection.OUTBOUND,
                content="assistant reply",
                role="assistant",
                model="test-model",
                provider="unit",
                token_count=42,
                reasoning_level="standard",
                trace_id="trace",
                conversation_episode_id="episode",
                principal="operator",
                created_at=datetime.now(UTC),
            ),
        )
        self.record_outbound_delivery_result = success(meta=_meta(), payload=True)
        self.record_response_result = success(meta=_meta(), payload=True)
        self.create_session_result = success(
            meta=_meta(),
            payload=SessionRecord(
                id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
                focus=None,
                focus_token_count=None,
                dialogue_summary=None,
                dialogue_summary_token_count=None,
                dialogue_start_turn_id=None,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            ),
        )

    def record_inbound_turn(
        self,
        *,
        meta,
        session_id: str,
        message: str,
        instruction: InboundInstructionRecord | None = None,
    ):
        self.record_inbound_calls.append(
            _TurnCall(
                session_id=session_id,
                message=message,
                source=meta.source,
                principal=meta.principal,
            )
        )
        return self.record_inbound_result

    def assemble_snapshot(self, *, meta, session_id: str, exclude_latest: bool = True):
        self.assemble_snapshot_calls.append((session_id, meta.source))
        return self.assemble_result

    def record_outbound_candidate(
        self,
        *,
        meta,
        session_id: str,
        content: str,
        model: str,
        provider: str,
        token_count: int,
        reasoning_level: str,
    ):
        self.record_outbound_candidate_calls.append(
            _CandidateCall(
                session_id=session_id,
                content=content,
                model=model,
                provider=provider,
                token_count=token_count,
                reasoning_level=reasoning_level,
                source=meta.source,
                principal=meta.principal,
            )
        )
        return self.record_outbound_candidate_result

    def record_outbound_delivery(
        self,
        *,
        meta,
        session_id: str,
        turn_id: str,
        delivered: bool,
    ):
        self.record_outbound_delivery_calls.append(
            _DeliveryCall(
                session_id=session_id,
                turn_id=turn_id,
                delivered=delivered,
                source=meta.source,
                principal=meta.principal,
            )
        )
        return self.record_outbound_delivery_result

    def assemble_context(
        self,
        *,
        meta,
        session_id: str,
        message: str,
        instruction: InboundInstructionRecord | None = None,
    ):
        del instruction
        self.assemble_calls.append(
            _AssembleCall(
                session_id=session_id,
                message=message,
                source=meta.source,
                principal=meta.principal,
            )
        )
        return self.turn_context_result

    def record_response(
        self,
        *,
        meta,
        session_id: str,
        content: str,
        model: str,
        provider: str,
        token_count: int,
        reasoning_level: str,
    ):
        self.record_response_calls.append(
            _RecordResponseCall(
                session_id=session_id,
                content=content,
                model=model,
                provider=provider,
                token_count=token_count,
                reasoning_level=reasoning_level,
                source=meta.source,
                principal=meta.principal,
            )
        )
        return self.record_response_result

    def update_focus(self, *, meta, session_id: str, content: str):
        del meta, session_id, content
        raise NotImplementedError

    def clear_session(self, *, meta, session_id: str):
        del meta, session_id
        raise NotImplementedError

    def compact_dialogue(self, *, meta, session_id: str):
        del meta, session_id
        raise NotImplementedError

    def create_session(self, *, meta):
        self.create_session_calls.append((meta.source, meta.principal))
        return self.create_session_result

    def get_latest_or_create_session(self, *, meta):
        self.get_latest_or_create_session_calls.append((meta.source, meta.principal))
        return self.create_session_result

    def get_session(self, *, meta, session_id: str):
        del meta, session_id
        raise NotImplementedError

    def health(self, *, meta):
        del meta
        raise NotImplementedError


def _meta():
    """Build valid envelope metadata for MAS route-test responses."""
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def _client() -> tuple[TestClient, _FakeMemoryAuthorityService]:
    """Create one FastAPI test client with the MAS route adapter mounted."""
    app = create_app()
    router = APIRouter()
    service = _FakeMemoryAuthorityService()
    register_routes(router=router, service=service)
    app.include_router(router)
    return TestClient(app), service


def test_assemble_context_route_forwards_request_and_returns_payload() -> None:
    """assemble_context route should forward arguments and return serialized payload."""
    client, service = _client()

    response = client.post(
        "/memory/assemble_context",
        json={
            "source": "sdk",
            "principal": "operator",
            "session_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "message": "hello",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["payload"]["session_id"] == "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    assert payload["payload"]["inbound_turn"]["content"] == "hello"
    assert payload["payload"]["context"]["current_focus"] == "current focus"
    assert (
        payload["payload"]["context"]["recent_conversation_summary"] == "prior summary"
    )
    assert payload["payload"]["context"]["recent_turns"][0]["content"] == "hello"
    assert payload["errors"] == []
    assert service.assemble_calls == [
        _AssembleCall(
            session_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
            message="hello",
            source="sdk",
            principal="operator",
        )
    ]


def test_record_response_route_forwards_request_and_maps_errors() -> None:
    """record_response route should serialize payloads and mapped error metadata."""
    client, service = _client()
    service.record_response_result = failure(
        meta=_meta(),
        errors=[validation_error("token_count must be >= 0")],
    )

    response = client.post(
        "/memory/record_response",
        json={
            "source": "sdk",
            "principal": "operator",
            "session_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "content": "assistant reply",
            "model": "test-model",
            "provider": "unit",
            "token_count": -1,
            "reasoning_level": "standard",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["payload"] is None
    assert payload["errors"][0]["category"] == "validation"
    assert service.record_response_calls == [
        _RecordResponseCall(
            session_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
            content="assistant reply",
            model="test-model",
            provider="unit",
            token_count=-1,
            reasoning_level="standard",
            source="sdk",
            principal="operator",
        )
    ]


def test_record_inbound_turn_route_returns_turn_payload() -> None:
    """record_inbound_turn route should serialize the recorded turn row."""
    client, service = _client()

    response = client.post(
        "/memory/record_inbound_turn",
        json={
            "source": "sdk",
            "principal": "operator",
            "session_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "message": "hello",
            "instruction": {
                "sender_e164": "+12025550100",
                "message_text": "hello",
                "timestamp_ms": 1,
                "source_device": "1",
                "source": "signal",
                "group_id": None,
                "quote_target_timestamp_ms": None,
                "reaction_target_timestamp_ms": None,
                "reaction_emoji": None,
                "approval_intent": None,
                "reply_to_proposal_token": None,
                "reaction_to_proposal_token": None,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["payload"]["direction"] == "inbound"
    assert payload["payload"]["content"] == "hello"
    assert service.record_inbound_calls == [
        _TurnCall(
            session_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
            message="hello",
            source="sdk",
            principal="operator",
        )
    ]


def test_assemble_snapshot_route_returns_context_without_live_turn() -> None:
    """assemble_snapshot route should return the historical snapshot payload."""
    client, service = _client()

    response = client.post(
        "/memory/assemble_snapshot",
        json={
            "source": "sdk",
            "principal": "operator",
            "session_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["payload"]["recent_turns"][0]["content"] == "hello"
    assert service.assemble_snapshot_calls == [("01ARZ3NDEKTSV4RRFFQ69G5FAV", "sdk")]


def test_record_outbound_candidate_and_delivery_routes_round_trip() -> None:
    """Outbound candidate and delivery routes should serialize their payloads."""
    client, service = _client()

    candidate = client.post(
        "/memory/record_outbound_candidate",
        json={
            "source": "sdk",
            "principal": "operator",
            "session_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "content": "assistant reply",
            "model": "test-model",
            "provider": "unit",
            "token_count": 42,
            "reasoning_level": "standard",
        },
    )
    delivery = client.post(
        "/memory/record_outbound_delivery",
        json={
            "source": "sdk",
            "principal": "operator",
            "session_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "turn_id": "turn-outbound",
            "delivered": True,
        },
    )

    assert candidate.status_code == 200
    assert candidate.json()["payload"]["content"] == "assistant reply"
    assert delivery.status_code == 200
    assert delivery.json()["payload"] is True
    assert service.record_outbound_candidate_calls == [
        _CandidateCall(
            session_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
            content="assistant reply",
            model="test-model",
            provider="unit",
            token_count=42,
            reasoning_level="standard",
            source="sdk",
            principal="operator",
        )
    ]
    assert service.record_outbound_delivery_calls == [
        _DeliveryCall(
            session_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
            turn_id="turn-outbound",
            delivered=True,
            source="sdk",
            principal="operator",
        )
    ]


def test_create_session_route_returns_session_id_only() -> None:
    """create_session route should publish only the created session identifier."""
    client, service = _client()

    response = client.post(
        "/memory/create_session",
        json={
            "source": "agent",
            "principal": "agent",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        "errors": [],
    }
    assert service.create_session_calls == [("agent", "agent")]


def test_get_latest_or_create_session_route_returns_session_id_only() -> None:
    """get_latest_or_create_session should return only the resolved session id."""
    client, service = _client()

    response = client.post(
        "/memory/get_latest_or_create_session",
        json={
            "source": "agent",
            "principal": "agent",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        "errors": [],
    }
    assert service.get_latest_or_create_session_calls == [("agent", "agent")]
