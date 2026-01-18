"""Capability-scoped context tokens for skill execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable
from uuid import uuid4

from .registry_schema import AutonomyLevel


@dataclass(frozen=True)
class SkillContext:
    """Execution context for skills, including capabilities and provenance."""

    allowed_capabilities: set[str]
    actor: str | None = None
    channel: str | None = None
    max_autonomy: AutonomyLevel | None = None
    confirmed: bool = False
    approval_token: str | None = None
    trace_id: str = field(default_factory=lambda: uuid4().hex)
    invocation_id: str = field(default_factory=lambda: uuid4().hex)
    parent_invocation_id: str | None = None

    def child(self, requested_capabilities: Iterable[str]) -> "SkillContext":
        """Create a child context constrained to requested capabilities."""
        requested = set(requested_capabilities)
        allowed = self.allowed_capabilities.intersection(requested)
        return SkillContext(
            allowed_capabilities=allowed,
            actor=self.actor,
            channel=self.channel,
            max_autonomy=self.max_autonomy,
            confirmed=self.confirmed,
            approval_token=self.approval_token,
            trace_id=self.trace_id,
            parent_invocation_id=self.invocation_id,
        )
