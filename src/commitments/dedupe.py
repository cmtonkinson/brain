"""LLM-driven commitment deduplication helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Iterable, Literal

from sqlalchemy.orm import Session

from commitments.constants import COMMITMENT_STATES
from config import settings
from llm import LLMClient, llm_client
from models import Commitment
from prompts import render_prompt


@dataclass(frozen=True)
class DedupeCandidate:
    """Candidate commitment for deduplication comparison."""

    commitment_id: int
    description: str


@dataclass(frozen=True)
class DedupeMatch:
    """LLM-provided match result for a candidate."""

    commitment_id: int | None
    confidence: float
    summary: str


@dataclass(frozen=True)
class DedupeProposal:
    """Proposal surfaced when a potential duplicate is detected."""

    candidate: DedupeCandidate
    confidence: float
    summary: str
    threshold: float


@dataclass(frozen=True)
class DedupeDecisionOutcome:
    """Outcome of an operator decision about a dedupe proposal."""

    status: Literal["duplicate", "not_duplicate"]
    allow_create: bool
    proposal: DedupeProposal


def resolve_dedupe_confidence_threshold() -> float:
    """Return the configured dedupe confidence threshold."""
    return settings.commitments.dedupe_confidence_threshold


def resolve_dedupe_summary_length() -> int:
    """Return the configured dedupe summary word limit."""
    return settings.commitments.dedupe_summary_length


def list_open_commitments(
    session_factory: Callable[[], Session],
) -> list[DedupeCandidate]:
    """Return OPEN commitments for dedupe comparison."""
    open_state = "OPEN"
    if open_state not in COMMITMENT_STATES:
        raise ValueError("OPEN is not a valid commitment state.")
    with session_factory() as session:
        rows = (
            session.query(Commitment.commitment_id, Commitment.description)
            .filter(Commitment.state == open_state)
            .order_by(Commitment.commitment_id.asc())
            .all()
        )
        return [
            DedupeCandidate(commitment_id=row.commitment_id, description=row.description)
            for row in rows
        ]


def generate_dedupe_proposal(
    *,
    description: str,
    candidates: Iterable[DedupeCandidate],
    client: LLMClient | None = None,
    threshold: float | None = None,
    summary_word_limit: int | None = None,
) -> DedupeProposal | None:
    """Compare a new commitment to candidates and return a proposal if duplicated."""
    candidate_list = list(candidates)
    if not candidate_list:
        return None

    resolved_threshold = resolve_dedupe_confidence_threshold() if threshold is None else threshold
    resolved_word_limit = (
        resolve_dedupe_summary_length() if summary_word_limit is None else summary_word_limit
    )
    resolved_client = client or llm_client

    match = _compare_with_llm(
        description=description,
        candidates=candidate_list,
        summary_word_limit=resolved_word_limit,
        client=resolved_client,
    )

    if match.commitment_id is None or match.confidence < resolved_threshold:
        return None

    candidate = _find_candidate(candidate_list, match.commitment_id)
    capped_summary = _cap_summary_words(match.summary, resolved_word_limit)
    return DedupeProposal(
        candidate=candidate,
        confidence=match.confidence,
        summary=capped_summary,
        threshold=resolved_threshold,
    )


def mark_not_duplicate(proposal: DedupeProposal) -> DedupeDecisionOutcome:
    """Return outcome for operator confirming not-duplicate."""
    return DedupeDecisionOutcome(
        status="not_duplicate",
        allow_create=True,
        proposal=proposal,
    )


def mark_is_duplicate(proposal: DedupeProposal) -> DedupeDecisionOutcome:
    """Return outcome for operator confirming duplicate."""
    return DedupeDecisionOutcome(
        status="duplicate",
        allow_create=False,
        proposal=proposal,
    )


def _compare_with_llm(
    *,
    description: str,
    candidates: list[DedupeCandidate],
    summary_word_limit: int,
    client: LLMClient,
) -> DedupeMatch:
    """Call the LLM to compare a new commitment against candidate commitments."""
    prompt = render_prompt(
        "commitments/dedupe",
        {
            "new_description": description.strip(),
            "candidates": _format_candidates(candidates),
            "summary_word_limit": summary_word_limit,
        },
    )
    response = client.complete_sync(
        messages=[
            {"role": "system", "content": "You are a careful JSON-only classifier."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
        max_tokens=400,
    )
    data = _parse_llm_response(response)
    confidence = _parse_confidence(data.get("confidence"))
    summary = str(data.get("summary") or "").strip()
    commitment_id = data.get("duplicate_commitment_id")
    commitment_id = int(commitment_id) if commitment_id is not None else None
    return DedupeMatch(
        commitment_id=commitment_id,
        confidence=confidence,
        summary=summary,
    )


def _format_candidates(candidates: Iterable[DedupeCandidate]) -> str:
    """Format candidate commitments for prompt injection."""
    lines = [f"{candidate.commitment_id}: {candidate.description}" for candidate in candidates]
    return "\n".join(lines)


def _parse_llm_response(response: str) -> dict:
    """Parse the JSON body from the LLM response."""
    raw = response.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("LLM response did not include JSON object.")
    payload = raw[start : end + 1]
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("LLM response JSON could not be parsed.") from exc
    if not isinstance(data, dict):
        raise ValueError("LLM response JSON must be an object.")
    return data


def _parse_confidence(value: object) -> float:
    """Parse a numeric confidence value."""
    try:
        confidence = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("LLM confidence must be a number.") from exc
    if confidence < 0.0 or confidence > 1.0:
        raise ValueError("LLM confidence must be between 0 and 1.")
    return confidence


def _find_candidate(
    candidates: Iterable[DedupeCandidate],
    commitment_id: int,
) -> DedupeCandidate:
    """Return the candidate with the matching commitment ID."""
    for candidate in candidates:
        if candidate.commitment_id == commitment_id:
            return candidate
    raise ValueError(f"Unknown commitment id returned by LLM: {commitment_id}")


def _cap_summary_words(summary: str, max_words: int) -> str:
    """Cap summary length to the configured word limit."""
    words = summary.split()
    if len(words) <= max_words:
        return summary.strip()
    return " ".join(words[:max_words]).strip()


__all__ = [
    "DedupeCandidate",
    "DedupeDecisionOutcome",
    "DedupeMatch",
    "DedupeProposal",
    "generate_dedupe_proposal",
    "list_open_commitments",
    "mark_is_duplicate",
    "mark_not_duplicate",
    "resolve_dedupe_confidence_threshold",
    "resolve_dedupe_summary_length",
]
