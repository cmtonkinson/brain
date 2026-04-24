"""Cooperative cancellation primitives for the headless agent loop."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CancelReason(StrEnum):
    """Reasons the loop may be asked to stop before reaching a final response."""

    manual = "manual"
    budget_tokens = "budget_tokens"
    budget_turns = "budget_turns"
    budget_wallclock = "budget_wallclock"
    parent_canceled = "parent_canceled"
    actor_lost = "actor_lost"


@dataclass(frozen=True, slots=True)
class CancelDecision:
    """Outcome of one cooperative cancellation checkpoint."""

    should_stop: bool
    reason: CancelReason | None = None


@dataclass(frozen=True, slots=True)
class TurnSummary:
    """Per-turn observation reported to a ``record_turn`` callback.

    Token deltas are deliberately NOT included on this struct: the caller
    of the loop is expected to fetch authoritative token totals from the
    Language Service audit trail (keyed by ``trace_id``) when budget
    evaluation is required. The loop only signals "another turn just
    completed; here is its index" so the caller can checkpoint.
    """

    turn_index: int


class CancellationError(Exception):
    """Raised by the loop when a cooperative checkpoint asks it to stop."""

    def __init__(self, reason: CancelReason) -> None:
        super().__init__(f"loop canceled: {reason.value}")
        self.reason = reason
