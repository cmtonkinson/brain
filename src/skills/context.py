"""Capability-scoped context tokens for skill execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable
from uuid import uuid4

from .registry_schema import AutonomyLevel


@dataclass(frozen=True)
class SkillContext:
    allowed_capabilities: set[str]
    actor: str | None = None
    channel: str | None = None
    max_autonomy: AutonomyLevel | None = None
    confirmed: bool = False
    invocation_id: str = field(default_factory=lambda: uuid4().hex)
    parent_invocation_id: str | None = None

    def child(self, requested_capabilities: Iterable[str]) -> "SkillContext":
        requested = set(requested_capabilities)
        allowed = self.allowed_capabilities.intersection(requested)
        return SkillContext(
            allowed_capabilities=allowed,
            actor=self.actor,
            channel=self.channel,
            max_autonomy=self.max_autonomy,
            confirmed=self.confirmed,
            parent_invocation_id=self.invocation_id,
        )
