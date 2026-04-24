"""``TurnState`` Protocol shared by Agent and Subagent runtimes.

:class:`AgentToolModel` needs four behaviours from a turn state object:

* a stable ``conversation_episode_id`` for the duration of the turn,
* a mutable ``language_recovery_notice_sent`` flag so the operator-facing
  recovery notice surfaces at most once per turn,
* a ``channel`` string used by recovery notification (operator path),
* a ``next_model_meta()`` factory that mints fresh trace/envelope metadata
  for each Language request inside the turn.

The operator-facing Agent uses a richer turn-state dataclass that also
tracks pending invocations and approval workflow; the headless Subagent
uses :class:`DefaultTurnState`, which is just enough to satisfy the
Protocol and produce stable telemetry IDs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from lib.sdk.meta import MetaOverrides
from lib.shared.ids import generate_ulid_str


class TurnState(Protocol):
    """Minimal turn-local state surface required by ``AgentToolModel``."""

    conversation_episode_id: str
    language_recovery_notice_sent: bool
    channel: str

    def next_model_meta(self) -> MetaOverrides:
        """Allocate metadata for one Language request within the active turn."""

    def nested_call_meta(self) -> MetaOverrides | None:
        """Return metadata for one nested SDK call under the current model node.

        May return ``None`` when no trace has been opened on the turn yet;
        callers must tolerate the optional value (the operator-recovery
        notification flow uses this to attribute its inline op call to
        the current Language span).
        """


@dataclass(slots=True)
class DefaultTurnState:
    """Headless turn-state implementation suitable for non-conversational drivers.

    Each instance owns one ``trace_id`` (auto-generated on construction
    when not supplied) and stamps a fresh ``envelope_id`` per
    ``next_model_meta`` call. Satisfies the :class:`TurnState` Protocol;
    richer agent-only state (approval tokens, pending-invocation map,
    frozen tool sets) is intentionally absent.
    """

    conversation_episode_id: str = ""
    language_recovery_notice_sent: bool = False
    channel: str = ""
    trace_id: str = field(default_factory=generate_ulid_str)
    root_envelope_id: str = field(default_factory=generate_ulid_str)
    current_model_envelope_id: str = ""

    def next_model_meta(self) -> MetaOverrides:
        """Return fresh metadata for the next Language call inside this turn."""
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


__all__ = ["DefaultTurnState", "TurnState"]
