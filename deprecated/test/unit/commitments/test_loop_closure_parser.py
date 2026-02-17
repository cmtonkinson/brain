"""Unit tests for loop-closure response parsing."""

from __future__ import annotations

from datetime import date

from commitments.loop_closure_parser import parse_loop_closure_response


def test_complete_keyword_parses_intent() -> None:
    """Responses with completion keywords should map to complete intent."""
    intent = parse_loop_closure_response("Done with it.")

    assert intent is not None
    assert intent.intent == "complete"


def test_cancel_keyword_parses_intent() -> None:
    """Responses with cancel keywords should map to cancel intent."""
    intent = parse_loop_closure_response("Please cancel this.")

    assert intent is not None
    assert intent.intent == "cancel"


def test_date_pattern_parses_renegotiate_intent() -> None:
    """Date patterns should map to renegotiate intents."""
    intent = parse_loop_closure_response("Reschedule to 2026-02-15.")

    assert intent is not None
    assert intent.intent == "renegotiate"
    assert intent.new_due_by == date(2026, 2, 15)


def test_review_keyword_parses_intent() -> None:
    """Responses with review keywords should map to review intent."""
    intent = parse_loop_closure_response("Review.")

    assert intent is not None
    assert intent.intent == "review"


def test_ambiguous_response_returns_none() -> None:
    """Unrecognized responses should return no intent."""
    intent = parse_loop_closure_response("Maybe later?")

    assert intent is None
