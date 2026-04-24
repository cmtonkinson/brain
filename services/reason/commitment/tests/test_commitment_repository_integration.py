"""Real-provider integration tests for Commitment Service Postgres repository."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from services.reason.commitment.data.repository import (
    PostgresCommitmentRepository,
)
from services.reason.commitment.data.runtime import (
    CommitmentPostgresRuntime,
)
from services.reason.commitment.domain import (
    CommitmentState,
)
from tests.integration.helpers import real_provider_tests_enabled

pytest_plugins = ("tests.integration.fixtures",)

pytestmark = pytest.mark.skipif(
    not real_provider_tests_enabled(),
    reason="set BRAIN_RUN_INTEGRATION_REAL=1 to run real-provider integration tests",
)


def _repo(settings) -> PostgresCommitmentRepository:
    runtime = CommitmentPostgresRuntime.from_settings(settings)
    return PostgresCommitmentRepository(runtime.schema_sessions)


def test_commitment_create_and_read_roundtrip(
    migrated_integration_settings,
) -> None:
    """Repository should persist and read back one commitment."""
    repo = _repo(migrated_integration_settings)
    now = datetime.now(UTC)

    commitment = repo.create_commitment(
        description="Integration test commitment",
        state="OPEN",
        provenance_reference=None,
        ingestion_id=None,
        source="test",
        importance=2,
        effort_provided=1,
        effort_inferred=None,
        urgency=1,
        due_by=now + timedelta(days=7),
        due_timezone="UTC",
        created_at=now,
    )
    assert commitment.id
    assert commitment.description == "Integration test commitment"
    assert commitment.state == CommitmentState.OPEN

    fetched = repo.get_commitment(commitment_id=commitment.id)
    assert fetched is not None
    assert fetched.id == commitment.id
    assert fetched.importance == 2


def test_commitment_transition_and_progress(
    migrated_integration_settings,
) -> None:
    """Repository should record transitions and progress entries."""
    repo = _repo(migrated_integration_settings)
    now = datetime.now(UTC)

    commitment = repo.create_commitment(
        description="Transition test commitment",
        state="OPEN",
        provenance_reference=None,
        ingestion_id=None,
        source="test",
        importance=3,
        effort_provided=2,
        effort_inferred=None,
        urgency=2,
        due_by=now + timedelta(days=3),
        due_timezone="UTC",
        created_at=now,
    )

    repo.create_progress_record(
        commitment_id=commitment.id,
        provenance_reference="ref-1",
        occurred_at=now,
        summary="Made progress",
        snippet="Details here",
        created_at=now,
    )

    progress = repo.list_progress(commitment_id=commitment.id)
    assert len(progress) == 1
    assert progress[0].summary == "Made progress"

    repo.create_transition_record(
        commitment_id=commitment.id,
        from_state="OPEN",
        to_state="COMPLETED",
        actor="operator",
        reason="Done",
        confidence=1.0,
        created_at=now,
        ever_missed_at=None,
    )

    transitions = repo.list_transitions(
        commitment_id=commitment.id,
    )
    assert len(transitions) >= 1
    assert transitions[0].to_state == "COMPLETED"

    updated = repo.get_commitment(commitment_id=commitment.id)
    assert updated is not None
    assert updated.state == CommitmentState.COMPLETED


def test_creation_proposal_roundtrip(
    migrated_integration_settings,
) -> None:
    """Repository should persist and decide creation proposals."""
    repo = _repo(migrated_integration_settings)
    now = datetime.now(UTC)

    proposal = repo.create_creation_proposal(
        description="Proposed commitment",
        provenance_reference="ref-proposal",
        ingestion_id=None,
        source="test",
        due_by=now + timedelta(days=5),
        due_timezone="UTC",
        importance=2,
        effort_provided=1,
        effort_inferred=1,
        requested_by="service",
        confidence=0.95,
        created_at=now,
        matched_commitment_id=None,
        match_summary=None,
        dedupe_confidence=None,
    )
    assert proposal.id
    assert proposal.status.value == "PENDING"

    fetched = repo.get_creation_proposal(proposal_id=proposal.id)
    assert fetched is not None
    assert fetched.description == "Proposed commitment"

    repo.decide_creation_proposal(
        proposal_id=proposal.id,
        status="APPROVED",
        decided_by="operator",
        decision_reason="Looks good",
        decided_at=now,
        created_commitment_id=None,
    )

    decided = repo.get_creation_proposal(proposal_id=proposal.id)
    assert decided is not None
    assert decided.status.value == "APPROVED"
