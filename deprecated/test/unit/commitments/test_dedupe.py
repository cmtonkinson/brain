"""Unit tests for commitment deduplication helpers."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy.orm import sessionmaker

from commitments.dedupe import (
    DedupeCandidate,
    generate_dedupe_proposal,
    list_open_commitments,
    mark_is_duplicate,
    mark_not_duplicate,
    resolve_dedupe_confidence_threshold,
    resolve_dedupe_summary_length,
)
from config import settings
from commitments.repository import CommitmentCreateInput, CommitmentRepository


@dataclass
class StubLLMClient:
    """Stub LLM client for deterministic test responses."""

    response: str

    def complete_sync(self, *args, **kwargs) -> str:  # noqa: ANN002, ANN003
        return self.response


def _create_commitment(
    factory: sessionmaker,
    *,
    description: str,
    state: str = "OPEN",
) -> int:
    repo = CommitmentRepository(factory)
    record = repo.create(
        CommitmentCreateInput(
            description=description,
            state=state,
        )
    )
    return record.commitment_id


def test_high_similarity_returns_proposal(sqlite_session_factory: sessionmaker) -> None:
    """High similarity results should yield a dedupe proposal."""
    commitment_id = _create_commitment(
        sqlite_session_factory,
        description="Book dentist appointment",
    )
    candidates = [
        DedupeCandidate(commitment_id=commitment_id, description="Book dentist appointment")
    ]
    client = StubLLMClient(
        response='{"duplicate_commitment_id": %d, "confidence": 0.92, "summary": "Same task"}'
        % commitment_id
    )

    proposal = generate_dedupe_proposal(
        description="Schedule dentist visit",
        candidates=candidates,
        client=client,
        threshold=0.8,
        summary_word_limit=10,
    )

    assert proposal is not None
    assert proposal.candidate.commitment_id == commitment_id
    assert proposal.confidence == pytest.approx(0.92)


def test_summary_length_is_capped() -> None:
    """Summaries should be capped at the configured word limit."""
    candidates = [DedupeCandidate(commitment_id=1, description="Submit tax return")]
    client = StubLLMClient(
        response=(
            '{"duplicate_commitment_id": 1, "confidence": 0.95, '
            '"summary": "one two three four five six"}'
        )
    )

    proposal = generate_dedupe_proposal(
        description="File taxes",
        candidates=candidates,
        client=client,
        threshold=0.5,
        summary_word_limit=3,
    )

    assert proposal is not None
    assert proposal.summary.split() == ["one", "two", "three"]


def test_similarity_below_threshold_returns_none() -> None:
    """Similarity below threshold should not yield a proposal."""
    candidates = [DedupeCandidate(commitment_id=2, description="Write weekly report")]
    client = StubLLMClient(
        response='{"duplicate_commitment_id": 2, "confidence": 0.2, "summary": "Low"}'
    )

    proposal = generate_dedupe_proposal(
        description="Draft report",
        candidates=candidates,
        client=client,
        threshold=0.8,
        summary_word_limit=10,
    )

    assert proposal is None


def test_non_open_commitments_excluded(sqlite_session_factory: sessionmaker) -> None:
    """Only OPEN commitments should be included in dedupe candidates."""
    open_id = _create_commitment(
        sqlite_session_factory,
        description="Open commitment",
        state="OPEN",
    )
    _create_commitment(
        sqlite_session_factory,
        description="Completed commitment",
        state="COMPLETED",
    )

    candidates = list_open_commitments(sqlite_session_factory)
    ids = [candidate.commitment_id for candidate in candidates]

    assert open_id in ids
    assert len(ids) == 1


def test_operator_decision_outcomes() -> None:
    """Operator decisions should allow or block creation."""
    proposal = generate_dedupe_proposal(
        description="Plan trip",
        candidates=[DedupeCandidate(commitment_id=3, description="Plan trip")],
        client=StubLLMClient(
            response='{"duplicate_commitment_id": 3, "confidence": 0.9, "summary": "Same"}'
        ),
        threshold=0.8,
        summary_word_limit=10,
    )
    assert proposal is not None

    allowed = mark_not_duplicate(proposal)
    blocked = mark_is_duplicate(proposal)

    assert allowed.allow_create is True
    assert blocked.allow_create is False


def test_dedupe_settings_resolve_from_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configured dedupe settings should be read from settings."""
    monkeypatch.setattr(settings.commitments, "dedupe_confidence_threshold", 0.42)
    monkeypatch.setattr(settings.commitments, "dedupe_summary_length", 12)

    assert resolve_dedupe_confidence_threshold() == pytest.approx(0.42)
    assert resolve_dedupe_summary_length() == 12
