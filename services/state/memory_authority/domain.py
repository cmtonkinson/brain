"""Domain models for Memory Authority Service payloads."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class BrainVerbosity(StrEnum):
    """Operator-facing verbosity profile options for assembled context."""

    TERSE = "terse"
    NORMAL = "normal"
    VERBOSE = "verbose"


class TurnDirection(StrEnum):
    """Dialogue turn direction values persisted by MAS."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


class ProfileContext(BaseModel):
    """Read-only profile context injected into each assembled context block."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operator_name: str
    brain_name: str
    brain_verbosity: BrainVerbosity


class DialogueTurn(BaseModel):
    """One assembled dialogue item for LLM context construction."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: str
    content: str
    is_summary: bool


class ContextBlock(BaseModel):
    """Full context bundle returned by MAS for each inbound turn."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    profile: ProfileContext
    focus: str | None
    dialogue: list[DialogueTurn]
    reference_snippets: list[str]


class SessionRecord(BaseModel):
    """Authoritative MAS session state row."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    focus: str | None
    focus_token_count: int | None
    dialogue_start_turn_id: str | None
    created_at: datetime
    updated_at: datetime


class FocusRecord(BaseModel):
    """Focus snapshot returned by explicit focus update operations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str
    content: str | None
    token_count: int | None
    updated_at: datetime


class TurnRecord(BaseModel):
    """Authoritative session dialogue turn row."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    session_id: str
    direction: TurnDirection
    content: str
    role: str
    model: str | None
    provider: str | None
    token_count: int | None
    reasoning_level: str | None
    trace_id: str
    principal: str
    created_at: datetime


class TurnSummaryRecord(BaseModel):
    """Authoritative summary row covering one inclusive turn range."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    session_id: str
    start_turn_id: str
    end_turn_id: str
    content: str
    token_count: int
    created_at: datetime


class HealthStatus(BaseModel):
    """MAS and Postgres readiness status payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    service_ready: bool
    substrate_ready: bool
    detail: str


def estimate_token_count(text: str) -> int:
    """Estimate token count using a simple word-based approximation."""
    words = len([item for item in text.split() if item])
    if words <= 0:
        return 0
    estimated = words * 3
    return (estimated + 1) // 2
