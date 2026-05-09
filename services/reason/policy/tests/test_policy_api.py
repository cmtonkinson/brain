"""Tests for Policy HTTP API routes."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi.testclient import TestClient

from lib.shared.envelope import EnvelopeKind, new_meta, success
from lib.shared.http.server import create_app
from services.reason.policy.api import register_routes
from services.reason.policy.domain import ApprovalProposalStatus
from services.reason.policy.service import PolicyService


class _FakePolicyService(PolicyService):
    """Programmable Policy fake for API route tests."""

    def __init__(self) -> None:
        self.last_status_token = ""
        self.last_response_token = ""
        self.last_response_intent = ""

    def authorize_and_execute(self, *, request, execute):
        raise NotImplementedError

    def health(self, *, meta):
        raise NotImplementedError

    def get_approval_proposal_status(self, *, meta, proposal_token: str):
        del meta
        self.last_status_token = proposal_token
        return success(
            meta=new_meta(kind=EnvelopeKind.EVENT, source="test", principal="operator"),
            payload=ApprovalProposalStatus(
                proposal_token=proposal_token,
                status="pending",
                op_id="demo-ping",
                actor="worker",
                channel="worker",
                expires_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        )

    def record_approval_response(self, *, meta, proposal_token: str, intent: str):
        del meta
        self.last_response_token = proposal_token
        self.last_response_intent = intent
        return success(
            meta=new_meta(kind=EnvelopeKind.EVENT, source="test", principal="operator"),
            payload=ApprovalProposalStatus(
                proposal_token=proposal_token,
                status="approved",
                op_id="demo-ping",
                actor="worker",
                channel="worker",
                expires_at=None,
            ),
        )


def _client() -> tuple[TestClient, _FakePolicyService]:
    app = create_app()
    router = APIRouter()
    service = _FakePolicyService()
    register_routes(router=router, service=service)
    app.include_router(router)
    return TestClient(app), service


def test_approval_status_route_returns_status_payload() -> None:
    """Approval status route should forward token and serialize status."""
    client, service = _client()

    response = client.post(
        "/policy/approval_status",
        json={
            "source": "worker",
            "principal": "operator",
            "proposal_token": "tok-123",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert service.last_status_token == "tok-123"
    assert body["payload"]["proposal_token"] == "tok-123"
    assert body["payload"]["status"] == "pending"
    assert body["errors"] == []


def test_approval_response_route_records_intent() -> None:
    """Approval response route should forward token and operator intent."""
    client, service = _client()

    response = client.post(
        "/policy/approval_response",
        json={
            "source": "signal",
            "principal": "operator",
            "proposal_token": "tok-123",
            "intent": "approve",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert service.last_response_token == "tok-123"
    assert service.last_response_intent == "approve"
    assert body["payload"]["status"] == "approved"
    assert body["errors"] == []
