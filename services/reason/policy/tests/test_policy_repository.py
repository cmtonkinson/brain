"""Unit tests for in-memory Policy Service persistence behavior."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from lib.shared.envelope import EnvelopeKind, new_meta
from services.reason.policy.data.repository import (
    InMemoryPolicyPersistenceRepository,
)
from services.reason.policy.domain import (
    ApprovalProposal,
    PolicyApprovalProposalRow,
    PolicyDecision,
    PolicyDecisionLogRow,
    PolicyDedupeLogRow,
    PolicyRegimeSnapshot,
)


def _proposal(token: str) -> ApprovalProposal:
    now = datetime.now(UTC)
    return ApprovalProposal(
        proposal_token=token,
        op_id="demo",
        op_version="1.0.0",
        summary="approval",
        actor="operator",
        channel="signal",
        trace_id="trace-1",
        invocation_id="inv-1",
        policy_regime_id="regime-1",
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )


def test_policy_repository_regime_upsert_is_hash_unique() -> None:
    repo = InMemoryPolicyPersistenceRepository()
    first = PolicyRegimeSnapshot(
        policy_regime_id="regime-a",
        policy_hash="hash-1",
        policy_json="{}",
        policy_id="policy",
        policy_version="1",
        created_at=datetime.now(UTC),
    )
    second = first.model_copy(update={"policy_regime_id": "regime-b"})
    row1 = repo.upsert_policy_regime(snapshot=first)
    row2 = repo.upsert_policy_regime(snapshot=second)
    assert row1.policy_regime_id == row2.policy_regime_id


def test_policy_repository_tracks_pending_proposals_and_status() -> None:
    repo = InMemoryPolicyPersistenceRepository()
    proposal = _proposal("token-1")
    repo.append_proposal(
        row=PolicyApprovalProposalRow(proposal=proposal, status="pending")
    )

    assert repo.find_pending_proposal(token="token-1") is not None

    repo.mark_proposal_status(token="token-1", status="approved")
    assert repo.find_pending_proposal(token="token-1") is None


def test_policy_repository_list_pending_proposals_excludes_expired_rows() -> None:
    repo = InMemoryPolicyPersistenceRepository()
    now = datetime.now(UTC)
    expired = _proposal("expired").model_copy(
        update={"expires_at": now - timedelta(seconds=1)}
    )
    active = _proposal("active").model_copy(
        update={"expires_at": now + timedelta(minutes=5)}
    )
    repo.append_proposal(
        row=PolicyApprovalProposalRow(proposal=expired, status="pending")
    )
    repo.append_proposal(
        row=PolicyApprovalProposalRow(proposal=active, status="pending")
    )

    rows = repo.list_pending_proposals(actor="operator", channel="signal", now=now)

    assert [row.proposal.proposal_token for row in rows] == ["active"]


def test_policy_repository_retention_trims_rows() -> None:
    repo = InMemoryPolicyPersistenceRepository()
    meta = new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")
    decision = PolicyDecision(
        decision_id="d1",
        policy_regime_id="r1",
        policy_regime_hash="h1",
        allowed=True,
        reason_codes=(),
        obligations=(),
        policy_metadata={},
        decided_at=datetime.now(UTC),
        policy_name="policy",
        policy_version="1",
    )
    repo.append_decision(
        row=PolicyDecisionLogRow(
            decision=decision,
            metadata=meta,
            actor="operator",
            channel="signal",
            op_id="demo",
        )
    )
    repo.append_dedupe(
        row=PolicyDedupeLogRow(
            dedupe_key="k",
            envelope_id=meta.envelope_id,
            trace_id=meta.trace_id,
            denied=False,
            window_seconds=60,
            created_at=datetime.now(UTC),
        )
    )
    repo.append_proposal(
        row=PolicyApprovalProposalRow(proposal=_proposal("token-2"), status="pending")
    )

    repo.trim_by_max_rows(max_rows=1)
    assert repo.count_decisions() == 1
    assert repo.count_dedupe() == 1
    assert repo.count_proposals() == 1
