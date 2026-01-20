"""Scheduled actor context helpers for execution and predicate evaluation flows."""

from __future__ import annotations

from dataclasses import dataclass

SCHEDULED_ACTOR_TYPE = "scheduled"
SCHEDULED_CHANNEL = "scheduled"
SCHEDULED_PRIVILEGE_LEVEL = "constrained"
SCHEDULED_AUTONOMY_LEVEL = "limited"


@dataclass(frozen=True)
class ScheduledActorContext:
    """Minimal scheduled actor context for Skills/Ops authorization and routing."""

    actor_type: str = SCHEDULED_ACTOR_TYPE
    channel: str = SCHEDULED_CHANNEL
    autonomy_level: str = SCHEDULED_AUTONOMY_LEVEL
    privilege_level: str = SCHEDULED_PRIVILEGE_LEVEL

    def to_reference(
        self,
        *,
        trigger_source: str | None = None,
        requested_by: str | None = None,
    ) -> str:
        """Return a compact, non-JSON reference string for audit and correlation."""
        parts = [
            f"actor_type={self.actor_type}",
            f"channel={self.channel}",
            f"autonomy={self.autonomy_level}",
            f"privilege={self.privilege_level}",
        ]
        if trigger_source:
            parts.append(f"trigger={trigger_source}")
        if requested_by:
            parts.append(f"requested_by={requested_by}")
        return "|".join(parts)
