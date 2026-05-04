"""Shared turn-local state for all Brain agent runtimes.

:class:`AgentToolModel` and the ``BrainToolset`` consume the
:class:`TurnState` Protocol for trace metadata, tool visibility, and
recovery-notice gating. :class:`DefaultTurnState` is the canonical
implementation used by both the operator-facing assistant and the
headless subagent; callers configure it via constructor arguments rather
than subclassing.

Tool-visibility fields (``active_tool_names``, ``always_on_op_ids``,
``denied_op_ids``) control which ops the model can see on each hop.
``active_tool_names`` is monotonically growing within a turn — tools are
added (via ``search_tools`` / ``get_tool_info``) but never removed.
Between turns, ``reset_active_tools`` resets to the always-on set plus
carry-forward from the prior turn.

Pending-invocation tracking (``remember_pending_invocation``,
``proposal_token_for_retry``) supports the approval-gating workflow
where a policy-denied op stores a proposal token for later retry.
Headless runtimes leave these empty.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from lib.sdk.meta import MetaOverrides
from lib.shared.ids import generate_ulid_str

# Discovery tool names are defined here (not in the assistant) because
# the turn state and toolset both need them for active-set management.
SEARCH_TOOLS_TOOL_NAME = "search_tools"
GET_TOOL_INFO_TOOL_NAME = "get_tool_info"
_DISCOVERY_TOOL_NAMES = frozenset({SEARCH_TOOLS_TOOL_NAME, GET_TOOL_INFO_TOOL_NAME})

MAX_PENDING_INVOCATIONS = 128


class TurnState(Protocol):
    """Turn-local state surface consumed by ``AgentToolModel`` and ``BrainToolset``."""

    actor: str
    channel: str
    conversation_episode_id: str
    language_recovery_notice_sent: bool
    active_tool_names: set[str]

    def next_model_meta(self) -> MetaOverrides:
        """Allocate metadata for one Language request within the active turn."""

    def nested_call_meta(self) -> MetaOverrides | None:
        """Return metadata for one nested SDK call under the current model node."""


@dataclass(frozen=True, slots=True)
class PendingInvocation:
    """Short-lived record for one approval-gated op attempt."""

    proposal_token: str
    op_id: str
    input_payload: dict[str, Any]
    actor: str
    channel: str
    approval: str
    reason_codes: tuple[str, ...]
    created_at: datetime
    expires_at: datetime | None = None


@dataclass(slots=True)
class DefaultTurnState:
    """Canonical turn-state implementation for all Brain agent runtimes.

    Headless callers (subagent) construct with ``all_op_ids`` pre-filled
    into ``always_on_op_ids`` so every op is visible from the start.
    Operator-facing callers (assistant) populate ``always_on_op_ids`` with
    only the statically-advertised set and rely on ``search_tools`` /
    ``get_tool_info`` to grow ``active_tool_names`` dynamically.
    """

    actor: str = "operator"
    channel: str = ""
    trace_id: str = field(default_factory=generate_ulid_str)
    conversation_episode_id: str = ""
    root_envelope_id: str = field(default_factory=generate_ulid_str)
    current_model_envelope_id: str = ""

    # Tool visibility --------------------------------------------------
    always_on_op_ids: frozenset[str] = frozenset()
    denied_op_ids: frozenset[str] = frozenset()
    active_tool_names: set[str] = field(default_factory=set)
    strip_keys: frozenset[str] = frozenset()

    # Approval gating --------------------------------------------------
    pending_invocations: dict[str, PendingInvocation] = field(default_factory=dict)
    reply_to_proposal_token: str = ""
    reaction_to_proposal_token: str = ""

    # Recovery ---------------------------------------------------------
    language_recovery_notice_sent: bool = False

    # -----------------------------------------------------------------
    # Tool visibility
    # -----------------------------------------------------------------

    def reset_active_tools(self) -> None:
        """Reset the active tool set to always-on ops plus carry-forward.

        Dynamically promoted ops from the prior turn are carried forward so
        multi-turn flows (e.g. an op that requires operator approval over a
        separate message) do not re-discover the same op every turn. Denied
        ops are always evicted.
        """
        carry_forward = {
            name
            for name in self.active_tool_names
            if name not in _DISCOVERY_TOOL_NAMES and name not in self.denied_op_ids
        }
        self.active_tool_names = {
            *(
                op_id
                for op_id in self.always_on_op_ids
                if op_id not in self.denied_op_ids
            ),
            *carry_forward,
            SEARCH_TOOLS_TOOL_NAME,
            GET_TOOL_INFO_TOOL_NAME,
        }

    # -----------------------------------------------------------------
    # Pending invocations (approval gating)
    # -----------------------------------------------------------------

    def prune_pending_invocations(self, *, now: datetime | None = None) -> None:
        """Evict expired and oldest-overflow pending approval records."""
        effective_now = now or datetime.now(UTC)
        expired_tokens = [
            token
            for token, pending in self.pending_invocations.items()
            if pending.expires_at is not None and pending.expires_at <= effective_now
        ]
        for token in expired_tokens:
            self.pending_invocations.pop(token, None)
        overflow = len(self.pending_invocations) - MAX_PENDING_INVOCATIONS
        if overflow <= 0:
            return
        oldest_tokens = [
            token
            for token, _pending in sorted(
                self.pending_invocations.items(),
                key=lambda item: item[1].created_at,
            )[:overflow]
        ]
        for token in oldest_tokens:
            self.pending_invocations.pop(token, None)

    def remember_pending_invocation(
        self,
        *,
        proposal_token: str,
        op_id: str,
        input_payload: dict[str, Any],
        approval: str,
        reason_codes: tuple[str, ...],
        expires_at: datetime | None = None,
        now: datetime | None = None,
    ) -> None:
        """Persist one short-lived approval-gated invocation attempt."""
        token = proposal_token.strip()
        if token == "":
            return
        effective_now = now or datetime.now(UTC)
        self.prune_pending_invocations(now=effective_now)
        self.pending_invocations[token] = PendingInvocation(
            proposal_token=token,
            op_id=op_id,
            input_payload=dict(input_payload),
            actor=self.actor,
            channel=self.channel,
            approval=approval,
            reason_codes=reason_codes,
            created_at=effective_now,
            expires_at=expires_at,
        )
        self.prune_pending_invocations(now=effective_now)

    def proposal_token_for_retry(
        self,
        *,
        op_id: str,
        input_payload: dict[str, Any],
    ) -> tuple[str, str]:
        """Return matched (reply_token, reaction_token) for one safe retry."""
        reply_token = self.reply_to_proposal_token.strip()
        reaction_token = self.reaction_to_proposal_token.strip()
        matched_reply = self._matching_pending_token(
            proposal_token=reply_token,
            op_id=op_id,
            input_payload=input_payload,
        )
        matched_reaction = self._matching_pending_token(
            proposal_token=reaction_token,
            op_id=op_id,
            input_payload=input_payload,
        )
        return matched_reply, matched_reaction

    def _matching_pending_token(
        self,
        *,
        proposal_token: str,
        op_id: str,
        input_payload: dict[str, Any],
    ) -> str:
        """Return a proposal token only when it matches a stored pending invocation."""
        token = proposal_token.strip()
        if token == "":
            return ""
        pending = self.pending_invocations.get(token)
        if pending is None:
            return ""
        if pending.op_id != op_id:
            return ""
        if pending.input_payload != input_payload:
            return ""
        return token

    # -----------------------------------------------------------------
    # Trace lifecycle
    # -----------------------------------------------------------------

    def begin_turn_trace(self) -> None:
        """Start one fresh trace context for the current operator turn."""
        self.trace_id = generate_ulid_str()
        self.root_envelope_id = generate_ulid_str()
        self.current_model_envelope_id = ""
        self.language_recovery_notice_sent = False

    def next_model_meta(self) -> MetaOverrides:
        """Allocate metadata for one Language request within the active turn trace."""
        envelope_id = generate_ulid_str()
        self.current_model_envelope_id = envelope_id
        return MetaOverrides(
            trace_id=self.trace_id or None,
            parent_id=self.root_envelope_id,
            envelope_id=envelope_id,
        )

    def nested_call_meta(self) -> MetaOverrides | None:
        """Return metadata for one nested SDK call under the current model node."""
        if self.trace_id == "":
            return None
        return MetaOverrides(
            trace_id=self.trace_id,
            parent_id=self.current_model_envelope_id or self.root_envelope_id,
        )

    # -----------------------------------------------------------------
    # OpInvocationContext conformance
    # -----------------------------------------------------------------

    def strip_input_payload(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Remove agent-only context properties from the input.

        Configure ``strip_keys`` at construction time to control which
        properties are removed. Default: empty (no stripping).
        """
        if not self.strip_keys:
            return input_payload
        return {k: v for k, v in input_payload.items() if k not in self.strip_keys}


__all__ = [
    "DefaultTurnState",
    "GET_TOOL_INFO_TOOL_NAME",
    "MAX_PENDING_INVOCATIONS",
    "PendingInvocation",
    "SEARCH_TOOLS_TOOL_NAME",
    "TurnState",
]
