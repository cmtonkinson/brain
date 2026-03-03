"""HTTP route adapter tests for Memory Authority Service."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter
from fastapi.testclient import TestClient

from packages.brain_shared.envelope import EnvelopeKind, failure, new_meta, success
from packages.brain_shared.errors import validation_error
from packages.brain_shared.http.server import create_app
from services.state.memory_authority.api import register_routes
from services.state.memory_authority.domain import (
    BrainVerbosity,
    ContextBlock,
    DialogueTurn,
    ProfileContext,
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


class _FakeMemoryAuthorityService(MemoryAuthorityService):
    """Programmable MAS fake for route-adapter tests."""

    def __init__(self) -> None:
        self.assemble_calls: list[_AssembleCall] = []
        self.record_response_calls: list[_RecordResponseCall] = []
        self.assemble_result = success(
            meta=_meta(),
            payload=ContextBlock(
                profile=ProfileContext(
                    operator_name="Operator",
                    brain_name="Brain",
                    brain_verbosity=BrainVerbosity.NORMAL,
                ),
                focus="current focus",
                dialogue=[DialogueTurn(role="user", content="hello", is_summary=False)],
                reference_snippets=[],
            ),
        )
        self.record_response_result = success(meta=_meta(), payload=True)

    def assemble_context(
        self,
        *,
        meta,
        session_id: str,
        message: str,
    ):
        self.assemble_calls.append(
            _AssembleCall(
                session_id=session_id,
                message=message,
                source=meta.source,
                principal=meta.principal,
            )
        )
        return self.assemble_result

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

    def create_session(self, *, meta):
        del meta
        raise NotImplementedError

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
    assert payload["payload"]["focus"] == "current focus"
    assert payload["payload"]["profile"]["brain_name"] == "Brain"
    assert payload["payload"]["dialogue"][0]["content"] == "hello"
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
