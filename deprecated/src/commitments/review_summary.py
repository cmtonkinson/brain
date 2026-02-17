"""Structured and natural language summaries for weekly commitment reviews."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.orm import Session

from commitments.repository import CommitmentRepository, CommitmentUpdateInput
from commitments.review_aggregation import ReviewCommitmentSets
from commitments.review_dedupe import ReviewDedupePair
from models import Commitment
from time_utils import to_utc


@dataclass(frozen=True)
class ReviewCommitmentSummary:
    """Serializable commitment snapshot for review summaries."""

    commitment_id: int
    description: str
    state: str
    due_by: str | None


@dataclass(frozen=True)
class ReviewDuplicateSummary:
    """Serializable summary of a potential duplicate pair."""

    primary: ReviewCommitmentSummary
    secondary: ReviewCommitmentSummary
    confidence: float
    summary: str
    threshold: float


@dataclass(frozen=True)
class ReviewStructuredSummary:
    """Structured payload for a weekly review summary."""

    completed: list[ReviewCommitmentSummary]
    missed: list[ReviewCommitmentSummary]
    modified: list[ReviewCommitmentSummary]
    no_due_by: list[ReviewCommitmentSummary]
    duplicates: list[ReviewDuplicateSummary]
    generated_at: str


@dataclass(frozen=True)
class ReviewSummaryResult:
    """Generated review summary output."""

    structured: ReviewStructuredSummary
    narrative: str


def generate_review_summary(
    session_factory: Callable[[], Session],
    *,
    review_sets: ReviewCommitmentSets,
    duplicates: list[ReviewDedupePair],
    generated_at: datetime | None = None,
) -> ReviewSummaryResult:
    """Generate structured and narrative summaries and update presentation timestamps."""
    timestamp = to_utc(generated_at or datetime.now(timezone.utc))
    structured = _build_structured_summary(
        session_factory,
        review_sets=review_sets,
        duplicates=duplicates,
        generated_at=timestamp,
    )
    _update_presented_for_review_at(
        session_factory,
        review_sets=review_sets,
        duplicates=duplicates,
        timestamp=timestamp,
    )
    narrative = _build_narrative(structured)
    return ReviewSummaryResult(structured=structured, narrative=narrative)


def _build_structured_summary(
    session_factory: Callable[[], Session],
    *,
    review_sets: ReviewCommitmentSets,
    duplicates: list[ReviewDedupePair],
    generated_at: datetime,
) -> ReviewStructuredSummary:
    """Build the structured summary payload for a review."""
    repo = CommitmentRepository(session_factory)
    return ReviewStructuredSummary(
        completed=[_commitment_to_summary(item) for item in review_sets.completed],
        missed=[_commitment_to_summary(item) for item in review_sets.missed],
        modified=[_commitment_to_summary(item) for item in review_sets.modified],
        no_due_by=[_commitment_to_summary(item) for item in review_sets.no_due_by],
        duplicates=[_duplicate_to_summary(pair, repo=repo) for pair in duplicates],
        generated_at=generated_at.isoformat(),
    )


def _commitment_to_summary(commitment: Commitment) -> ReviewCommitmentSummary:
    """Convert a commitment model to a serializable summary."""
    due_by = commitment.due_by
    due_by_iso = to_utc(due_by).isoformat() if due_by is not None else None
    return ReviewCommitmentSummary(
        commitment_id=commitment.commitment_id,
        description=commitment.description,
        state=str(commitment.state),
        due_by=due_by_iso,
    )


def _duplicate_to_summary(
    pair: ReviewDedupePair,
    *,
    repo: CommitmentRepository,
) -> ReviewDuplicateSummary:
    """Convert a duplicate candidate pair into a structured summary."""
    primary = _load_commitment(repo, pair.primary.commitment_id)
    secondary = _load_commitment(repo, pair.secondary.commitment_id)
    return ReviewDuplicateSummary(
        primary=_commitment_to_summary(primary),
        secondary=_commitment_to_summary(secondary),
        confidence=pair.confidence,
        summary=pair.summary,
        threshold=pair.threshold,
    )


def _load_commitment(
    repo: CommitmentRepository,
    commitment_id: int,
) -> Commitment:
    """Load a commitment or raise when missing."""
    commitment = repo.get_by_id(commitment_id)
    if commitment is None:
        raise ValueError(f"Commitment not found: {commitment_id}")
    return commitment


def _update_presented_for_review_at(
    session_factory: Callable[[], Session],
    *,
    review_sets: ReviewCommitmentSets,
    duplicates: list[ReviewDedupePair],
    timestamp: datetime,
) -> None:
    """Update presented_for_review_at for commitments included in the review."""
    commitment_ids = _collect_commitment_ids(review_sets, duplicates)
    if not commitment_ids:
        return
    repo = CommitmentRepository(session_factory)
    for commitment_id in commitment_ids:
        repo.update(
            commitment_id,
            CommitmentUpdateInput(presented_for_review_at=timestamp),
            now=timestamp,
        )


def _collect_commitment_ids(
    review_sets: ReviewCommitmentSets,
    duplicates: list[ReviewDedupePair],
) -> list[int]:
    """Collect unique commitment IDs included in review content."""
    ids: set[int] = set()
    for group in (
        review_sets.completed,
        review_sets.missed,
        review_sets.modified,
        review_sets.no_due_by,
    ):
        for item in group:
            ids.add(item.commitment_id)
    for pair in duplicates:
        ids.add(pair.primary.commitment_id)
        ids.add(pair.secondary.commitment_id)
    return sorted(ids)


def collect_commitment_ids_from_structured(
    structured: ReviewStructuredSummary,
) -> list[int]:
    """Collect commitment IDs from a structured review summary."""
    ids: set[int] = set()
    for group in (
        structured.completed,
        structured.missed,
        structured.modified,
        structured.no_due_by,
    ):
        for item in group:
            ids.add(item.commitment_id)
    for pair in structured.duplicates:
        ids.add(pair.primary.commitment_id)
        ids.add(pair.secondary.commitment_id)
    return sorted(ids)


def _build_narrative(summary: ReviewStructuredSummary) -> str:
    """Generate a neutral, non-judgmental narrative summary."""
    if _is_summary_empty(summary):
        return "Nothing new to review this week."
    lines: list[str] = ["Weekly review summary:"]
    _append_commitment_line(lines, "Completed", summary.completed)
    _append_commitment_line(lines, "Missed", summary.missed)
    _append_commitment_line(lines, "Modified", summary.modified)
    _append_commitment_line(lines, "No due date", summary.no_due_by)
    if summary.duplicates:
        lines.append(_format_duplicates_line(summary.duplicates))
    return " ".join(lines)


def _append_commitment_line(
    lines: list[str],
    label: str,
    items: list[ReviewCommitmentSummary],
) -> None:
    """Append a labeled line describing commitments when present."""
    if not items:
        return
    descriptions = ", ".join(item.description for item in items)
    lines.append(f"{label}: {descriptions}.")


def _format_duplicates_line(duplicates: list[ReviewDuplicateSummary]) -> str:
    """Format a line describing potential duplicate pairs."""
    pair_descriptions = []
    for duplicate in duplicates:
        pair_descriptions.append(
            f"{duplicate.primary.description} / {duplicate.secondary.description}"
        )
    pairs = "; ".join(pair_descriptions)
    return f"Potential duplicates flagged: {pairs}."


def _is_summary_empty(summary: ReviewStructuredSummary) -> bool:
    """Return True when the structured summary has no content."""
    return (
        not summary.completed
        and not summary.missed
        and not summary.modified
        and not summary.no_due_by
        and not summary.duplicates
    )


__all__ = [
    "ReviewCommitmentSummary",
    "ReviewDuplicateSummary",
    "ReviewStructuredSummary",
    "ReviewSummaryResult",
    "collect_commitment_ids_from_structured",
    "generate_review_summary",
]
