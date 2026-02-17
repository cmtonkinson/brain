"""Unit tests for review-time commitment deduplication."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from sqlalchemy.orm import sessionmaker

from commitments.repository import CommitmentCreateInput, CommitmentRepository
from commitments.review_dedupe import scan_review_duplicates
from config import settings


@dataclass
class SequencedLLMClient:
    """Stub LLM client that returns responses in order."""

    responses: list[str]
    index: int = field(default=0)

    def complete_sync(self, *args, **kwargs) -> str:  # noqa: ANN002, ANN003
        response = self.responses[self.index]
        self.index += 1
        return response


def _create_commitment(
    factory: sessionmaker,
    *,
    description: str,
    state: str = "OPEN",
) -> int:
    """Create a commitment record for review dedupe tests."""
    repo = CommitmentRepository(factory)
    record = repo.create(
        CommitmentCreateInput(
            description=description,
            state=state,
        )
    )
    return record.commitment_id


def test_review_dedupe_identifies_duplicates(sqlite_session_factory: sessionmaker) -> None:
    """Review dedupe should return duplicate pairs with capped summaries."""
    first_id = _create_commitment(
        sqlite_session_factory,
        description="Book dentist appointment",
    )
    second_id = _create_commitment(
        sqlite_session_factory,
        description="Schedule dentist visit",
    )
    client = SequencedLLMClient(
        responses=[
            (
                '{"duplicate_commitment_id": %d, "confidence": 0.95, '
                '"summary": "one two three four"}' % second_id
            )
        ]
    )

    matches = scan_review_duplicates(
        sqlite_session_factory,
        client=client,
        threshold=0.8,
        summary_word_limit=2,
    )

    assert len(matches) == 1
    match = matches[0]
    assert match.primary.commitment_id == first_id
    assert match.secondary.commitment_id == second_id
    assert match.summary.split() == ["one", "two"]


def test_review_dedupe_excludes_non_open_commitments(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Only OPEN commitments should be included in review dedupe scans."""
    open_first = _create_commitment(
        sqlite_session_factory,
        description="Prepare weekly report",
        state="OPEN",
    )
    _create_commitment(
        sqlite_session_factory,
        description="Completed report",
        state="COMPLETED",
    )
    open_second = _create_commitment(
        sqlite_session_factory,
        description="Draft weekly summary",
        state="OPEN",
    )
    client = SequencedLLMClient(
        responses=[
            (
                '{"duplicate_commitment_id": %d, "confidence": 0.9, '
                '"summary": "Similar work"}' % open_second
            )
        ]
    )

    matches = scan_review_duplicates(
        sqlite_session_factory,
        client=client,
        threshold=0.8,
        summary_word_limit=5,
    )

    assert len(matches) == 1
    ids = {matches[0].primary.commitment_id, matches[0].secondary.commitment_id}
    assert ids == {open_first, open_second}


def test_review_dedupe_returns_empty_when_no_duplicates(
    sqlite_session_factory: sessionmaker,
) -> None:
    """No matches should be returned when similarity is below threshold."""
    _create_commitment(
        sqlite_session_factory,
        description="Follow up with accountant",
    )
    second_id = _create_commitment(
        sqlite_session_factory,
        description="Book flight to NYC",
    )
    client = SequencedLLMClient(
        responses=[
            (
                '{"duplicate_commitment_id": %d, "confidence": 0.1, '
                '"summary": "Unrelated"}' % second_id
            )
        ]
    )

    matches = scan_review_duplicates(
        sqlite_session_factory,
        client=client,
        threshold=0.8,
        summary_word_limit=5,
    )

    assert matches == []


def test_review_dedupe_uses_configured_thresholds(
    sqlite_session_factory: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configured dedupe settings should be honored during review scan."""
    first_id = _create_commitment(
        sqlite_session_factory,
        description="Review contract",
    )
    second_id = _create_commitment(
        sqlite_session_factory,
        description="Read contract",
    )
    client = SequencedLLMClient(
        responses=[
            (
                '{"duplicate_commitment_id": %d, "confidence": 0.55, '
                '"summary": "one two three four five"}' % second_id
            )
        ]
    )
    monkeypatch.setattr(settings.commitments, "dedupe_confidence_threshold", 0.5)
    monkeypatch.setattr(settings.commitments, "dedupe_summary_length", 3)

    matches = scan_review_duplicates(
        sqlite_session_factory,
        client=client,
    )

    assert len(matches) == 1
    assert matches[0].primary.commitment_id == first_id
    assert matches[0].secondary.commitment_id == second_id
    assert matches[0].summary.split() == ["one", "two", "three"]
