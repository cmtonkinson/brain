"""Unit tests for weekly review summary generation."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

import json
from sqlalchemy.orm import sessionmaker

from commitments.dedupe import DedupeCandidate
from commitments.repository import CommitmentCreateInput, CommitmentRepository
from commitments.review_aggregation import ReviewCommitmentSets
from commitments.review_dedupe import ReviewDedupePair
from commitments.review_summary import generate_review_summary


def _create_commitment(
    factory: sessionmaker,
    *,
    description: str,
    state: str = "OPEN",
    reviewed_at: datetime | None = None,
) -> int:
    """Create a commitment record for review summary tests."""
    repo = CommitmentRepository(factory)
    record = repo.create(
        CommitmentCreateInput(
            description=description,
            state=state,
            reviewed_at=reviewed_at,
        )
    )
    return record.commitment_id


def _load_commitment(factory: sessionmaker, commitment_id: int):
    """Load a commitment record for assertions."""
    repo = CommitmentRepository(factory)
    record = repo.get_by_id(commitment_id)
    assert record is not None
    return record


def _normalize_timestamp(value: datetime) -> datetime:
    """Normalize timestamps to UTC for SQLite comparisons."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def test_review_summary_includes_all_categories(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Structured and narrative summaries should include all review categories."""
    completed_id = _create_commitment(
        sqlite_session_factory,
        description="Completed task",
        state="COMPLETED",
    )
    missed_id = _create_commitment(
        sqlite_session_factory,
        description="Missed task",
        state="MISSED",
    )
    modified_id = _create_commitment(
        sqlite_session_factory,
        description="Modified task",
        state="OPEN",
    )
    no_due_id = _create_commitment(
        sqlite_session_factory,
        description="No due date task",
        state="OPEN",
    )
    dup_primary_id = _create_commitment(
        sqlite_session_factory,
        description="Duplicate candidate A",
        state="OPEN",
    )
    dup_secondary_id = _create_commitment(
        sqlite_session_factory,
        description="Duplicate candidate B",
        state="OPEN",
    )

    review_sets = ReviewCommitmentSets(
        completed=[_load_commitment(sqlite_session_factory, completed_id)],
        missed=[_load_commitment(sqlite_session_factory, missed_id)],
        modified=[_load_commitment(sqlite_session_factory, modified_id)],
        no_due_by=[_load_commitment(sqlite_session_factory, no_due_id)],
        last_run_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    duplicates = [
        ReviewDedupePair(
            primary=DedupeCandidate(
                commitment_id=dup_primary_id,
                description="Duplicate candidate A",
            ),
            secondary=DedupeCandidate(
                commitment_id=dup_secondary_id,
                description="Duplicate candidate B",
            ),
            confidence=0.9,
            summary="Similar commitments",
            threshold=0.8,
        )
    ]
    generated_at = datetime(2024, 2, 1, tzinfo=timezone.utc)

    result = generate_review_summary(
        sqlite_session_factory,
        review_sets=review_sets,
        duplicates=duplicates,
        generated_at=generated_at,
    )

    structured = result.structured
    assert {item.commitment_id for item in structured.completed} == {completed_id}
    assert {item.commitment_id for item in structured.missed} == {missed_id}
    assert {item.commitment_id for item in structured.modified} == {modified_id}
    assert {item.commitment_id for item in structured.no_due_by} == {no_due_id}
    assert {item.primary.commitment_id for item in structured.duplicates} == {dup_primary_id}

    payload = asdict(structured)
    json.dumps(payload)

    narrative = result.narrative
    assert "Completed" in narrative
    assert "Missed" in narrative
    assert "Modified" in narrative
    assert "No due date" in narrative


def test_review_summary_handles_empty_review(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Empty review content should return a nothing-new message."""
    review_sets = ReviewCommitmentSets(
        completed=[],
        missed=[],
        modified=[],
        no_due_by=[],
        last_run_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    result = generate_review_summary(
        sqlite_session_factory,
        review_sets=review_sets,
        duplicates=[],
        generated_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
    )

    assert result.narrative == "Nothing new to review this week."
    assert result.structured.completed == []
    assert result.structured.duplicates == []


def test_review_summary_updates_presented_for_review_at_only_for_included(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Presented-for-review timestamps should only update for included commitments."""
    reviewed_at = datetime(2023, 12, 31, tzinfo=timezone.utc)
    included_id = _create_commitment(
        sqlite_session_factory,
        description="Included task",
        state="OPEN",
        reviewed_at=reviewed_at,
    )
    excluded_id = _create_commitment(
        sqlite_session_factory,
        description="Excluded task",
        state="OPEN",
    )

    review_sets = ReviewCommitmentSets(
        completed=[],
        missed=[],
        modified=[_load_commitment(sqlite_session_factory, included_id)],
        no_due_by=[],
        last_run_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    generated_at = datetime(2024, 2, 1, tzinfo=timezone.utc)

    generate_review_summary(
        sqlite_session_factory,
        review_sets=review_sets,
        duplicates=[],
        generated_at=generated_at,
    )

    included = _load_commitment(sqlite_session_factory, included_id)
    excluded = _load_commitment(sqlite_session_factory, excluded_id)

    assert _normalize_timestamp(included.presented_for_review_at) == generated_at
    assert _normalize_timestamp(included.reviewed_at) == reviewed_at
    assert excluded.presented_for_review_at is None
