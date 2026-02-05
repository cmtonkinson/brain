"""Unit tests for weekly review delivery and engagement."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from attention.router import RoutingResult
from commitments.repository import CommitmentCreateInput, CommitmentRepository
from commitments.review_delivery import deliver_review_summary, record_review_engagement
from commitments.review_summary import ReviewStructuredSummary, ReviewSummaryResult


@dataclass
class StubAttentionRouter:
    """Stub attention router capturing routed envelopes."""

    routed: list[object] = field(default_factory=list)

    async def route_envelope(self, envelope) -> RoutingResult:  # noqa: ANN001
        """Capture envelope and return a log-only result."""
        self.routed.append(envelope)
        return RoutingResult(decision="LOG_ONLY", channel=None)


def _create_commitment(factory: sessionmaker, *, description: str) -> int:
    """Create a commitment record for engagement tests."""
    repo = CommitmentRepository(factory)
    record = repo.create(CommitmentCreateInput(description=description))
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


def test_review_delivery_submits_notification() -> None:
    """Review delivery should submit a REVIEW notification to the router."""
    router = StubAttentionRouter()
    structured = ReviewStructuredSummary(
        completed=[],
        missed=[],
        modified=[],
        no_due_by=[],
        duplicates=[],
        generated_at="2024-02-01T00:00:00+00:00",
    )
    summary = ReviewSummaryResult(
        structured=structured,
        narrative="Nothing new to review this week.",
    )

    deliver_review_summary(
        router,
        review_id=42,
        summary=summary,
        owner="+15555550123",
        now=datetime(2024, 2, 1, tzinfo=timezone.utc),
    )

    assert len(router.routed) == 1
    envelope = router.routed[0]
    assert envelope.signal_type == "commitment.review"
    assert envelope.channel_hint == "signal"
    assert "Nothing new to review" in envelope.signal_payload.message
    assert "Structured summary" in envelope.signal_payload.message


def test_review_engagement_updates_reviewed_at(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Engagement should update reviewed_at for included commitments."""
    included_id = _create_commitment(
        sqlite_session_factory,
        description="Included commitment",
    )
    excluded_id = _create_commitment(
        sqlite_session_factory,
        description="Excluded commitment",
    )
    engaged_at = datetime(2024, 2, 2, tzinfo=timezone.utc)

    record_review_engagement(
        review_id=7,
        commitment_ids=[included_id],
        session_factory=sqlite_session_factory,
        engaged_at=engaged_at,
    )

    included = _load_commitment(sqlite_session_factory, included_id)
    excluded = _load_commitment(sqlite_session_factory, excluded_id)

    assert _normalize_timestamp(included.reviewed_at) == engaged_at
    assert excluded.reviewed_at is None
