"""Domain models for Recall Service payloads."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class TurnDirection(StrEnum):
    """Dialogue turn direction values persisted by Recall."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


class DialogueTurn(BaseModel):
    """One assembled dialogue item for LLM context construction."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: str
    content: str
    is_summary: bool
    timestamp_ms: int | None = None


class ContextBlock(BaseModel):
    """Full context bundle returned by Recall for each inbound turn."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    current_focus: str | None
    recent_conversation_summary: str
    recent_turns: list[DialogueTurn]
    reference_snippets: list[str]


class TurnContext(BaseModel):
    """Recall-resolved turn-start context for one inbound operator message."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str
    inbound_turn: "TurnRecord"
    context: ContextBlock


class InboundInstructionRecord(BaseModel):
    """Full inbound operator instruction metadata persisted with the turn."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sender_e164: str
    message_text: str
    timestamp_ms: int
    source_device: str
    source: str
    group_id: str | None = None
    quote_target_timestamp_ms: int | None = None
    reaction_target_timestamp_ms: int | None = None
    reaction_emoji: str | None = None
    approval_intent: str | None = None
    reply_to_proposal_token: str | None = None
    reaction_to_proposal_token: str | None = None


class OutboundDeliveryRecord(BaseModel):
    """Outbound candidate delivery outcome persisted with the assistant turn."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: Literal["candidate", "delivered", "failed"]
    delivered_at_ms: int | None = None
    detail: str | None = None


class ConversationalMemoryContext(BaseModel):
    """Recall-owned metadata required to persist one conversational outbound turn."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str
    model: str
    provider: str
    token_count: int
    reasoning_level: str


class SessionRecord(BaseModel):
    """Authoritative Recall session state row."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    focus: str | None
    focus_token_count: int | None
    dialogue_summary: str | None
    dialogue_summary_token_count: int | None
    dialogue_start_turn_id: str | None
    current_conversation_episode_id: str | None = None
    last_episode_inbound_at: datetime | None = None
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
    conversation_episode_id: str
    principal: str
    source: str | None = None
    sender_e164: str | None = None
    timestamp_ms: int | None = None
    source_device: str | None = None
    group_id: str | None = None
    quote_target_timestamp_ms: int | None = None
    reaction_target_timestamp_ms: int | None = None
    reaction_emoji: str | None = None
    approval_intent: str | None = None
    reply_to_proposal_token: str | None = None
    reaction_to_proposal_token: str | None = None
    delivery_state: Literal["candidate", "delivered", "failed"] | None = None
    delivery_timestamp_ms: int | None = None
    delivery_detail: str | None = None
    created_at: datetime


class HealthStatus(BaseModel):
    """Recall and Postgres readiness status payload."""

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
