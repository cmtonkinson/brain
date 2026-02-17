"""Keyword-based loop-closure response parsing helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from typing import Literal


@dataclass(frozen=True)
class LoopClosureIntent:
    """Structured intent extracted from a loop-closure response."""

    intent: Literal["complete", "cancel", "renegotiate", "review"]
    new_due_by: date | None = None


_COMPLETE_KEYWORDS = ("complete", "done", "finished")
_CANCEL_KEYWORDS = ("cancel", "canceled", "cancelled", "won't do", "wont do")
_REVIEW_KEYWORDS = ("review",)
_DATE_PATTERN = re.compile(r"\b(\d{4})[-/](\d{2})[-/](\d{2})\b")


def parse_loop_closure_response(text: str) -> LoopClosureIntent | None:
    """Parse a loop-closure response into a structured intent."""
    # TODO: Consider semantic parsing of loop-closure responses when intent is ambiguous.
    normalized = _normalize_text(text)
    if _contains_keyword(normalized, _COMPLETE_KEYWORDS):
        return LoopClosureIntent(intent="complete")
    if _contains_keyword(normalized, _CANCEL_KEYWORDS):
        return LoopClosureIntent(intent="cancel")
    if _contains_keyword(normalized, _REVIEW_KEYWORDS):
        return LoopClosureIntent(intent="review")
    match = _extract_date(normalized)
    if match is not None:
        return LoopClosureIntent(intent="renegotiate", new_due_by=match)
    return None


def _normalize_text(text: str) -> str:
    """Normalize response text for keyword matching."""
    return text.strip().lower().replace("’", "'")


def _contains_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    """Return True when any keyword appears in the text."""
    return any(keyword in text for keyword in keywords)


def _extract_date(text: str) -> date | None:
    """Return the first valid date parsed from supported patterns."""
    for match in _DATE_PATTERN.finditer(text):
        year, month, day = match.groups()
        try:
            return date(int(year), int(month), int(day))
        except ValueError:
            continue
    return None


__all__ = ["LoopClosureIntent", "parse_loop_closure_response"]
