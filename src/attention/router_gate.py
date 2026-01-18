"""Attention router gate enforcement and violation tracking."""

from __future__ import annotations

import logging
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_router_active: ContextVar[bool] = ContextVar("router_active", default=False)


class RouterViolationError(RuntimeError):
    """Raised when a direct notification attempt bypasses the router."""


@dataclass(frozen=True)
class RouterViolation:
    """Captured router violation metadata."""

    source_component: str
    channel: str
    reason: str
    timestamp: datetime


class InMemoryViolationRecorder:
    """In-memory recorder for router violations."""

    def __init__(self) -> None:
        """Initialize an empty violation recorder."""
        self._violations: list[RouterViolation] = []

    def record(self, violation: RouterViolation) -> None:
        """Record a router violation."""
        self._violations.append(violation)

    def list(self) -> list[RouterViolation]:
        """Return recorded violations."""
        return list(self._violations)

    def clear(self) -> None:
        """Clear recorded violations."""
        self._violations.clear()


_recorder = InMemoryViolationRecorder()


def get_violation_recorder() -> InMemoryViolationRecorder:
    """Return the shared violation recorder."""
    return _recorder


def activate_router_context() -> Token:
    """Activate the router context for outbound notifications."""
    return _router_active.set(True)


def deactivate_router_context(token: Token) -> None:
    """Deactivate the router context for outbound notifications."""
    _router_active.reset(token)


def ensure_router_context(source_component: str, channel: str) -> None:
    """Ensure outbound notifications pass through the attention router."""
    if _router_active.get():
        return
    violation = RouterViolation(
        source_component=source_component,
        channel=channel,
        reason="direct_notification_blocked",
        timestamp=datetime.now(timezone.utc),
    )
    logger.error("Direct notification blocked for %s/%s.", source_component, channel)
    _recorder.record(violation)
    raise RouterViolationError("Direct notification blocked by attention router gate.")
