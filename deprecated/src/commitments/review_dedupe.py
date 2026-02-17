"""Review-time duplicate detection for weekly commitment summaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

from commitments.dedupe import (
    DedupeCandidate,
    cap_summary_words,
    compare_with_llm,
    list_open_commitments,
    resolve_dedupe_confidence_threshold,
    resolve_dedupe_summary_length,
)
from llm import LLMClient, llm_client


@dataclass(frozen=True)
class ReviewDedupePair:
    """Potential duplicate pair identified during review preparation."""

    primary: DedupeCandidate
    secondary: DedupeCandidate
    confidence: float
    summary: str
    threshold: float


def scan_review_duplicates(
    session_factory: Callable[[], Session],
    *,
    client: LLMClient | None = None,
    threshold: float | None = None,
    summary_word_limit: int | None = None,
) -> list[ReviewDedupePair]:
    """Scan OPEN commitments for potential duplicates during weekly review prep."""
    candidates = list_open_commitments(session_factory)
    if len(candidates) < 2:
        return []

    resolved_threshold = resolve_dedupe_confidence_threshold() if threshold is None else threshold
    resolved_word_limit = (
        resolve_dedupe_summary_length() if summary_word_limit is None else summary_word_limit
    )
    resolved_client = client or llm_client

    matches: list[ReviewDedupePair] = []
    for idx, primary in enumerate(candidates):
        for secondary in candidates[idx + 1 :]:
            match = compare_with_llm(
                description=primary.description,
                candidates=[secondary],
                client=resolved_client,
                summary_word_limit=resolved_word_limit,
            )
            if match.commitment_id is None:
                continue
            if match.commitment_id != secondary.commitment_id:
                raise ValueError("LLM dedupe returned unknown commitment id for review comparison.")
            if match.confidence < resolved_threshold:
                continue
            summary = cap_summary_words(match.summary, resolved_word_limit)
            matches.append(
                ReviewDedupePair(
                    primary=primary,
                    secondary=secondary,
                    confidence=match.confidence,
                    summary=summary,
                    threshold=resolved_threshold,
                )
            )
    return matches


__all__ = [
    "ReviewDedupePair",
    "scan_review_duplicates",
]
