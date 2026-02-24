"""Transport-agnostic Signal adapter protocol and DTOs."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict


class SignalAdapterError(Exception):
    """Base exception for Signal adapter failures."""


class SignalAdapterDependencyError(SignalAdapterError):
    """Dependency-level adapter failure (network/upstream unavailable)."""


class SignalAdapterInternalError(SignalAdapterError):
    """Internal adapter failure (mapping or contract mismatch)."""


class SignalWebhookRegistrationResult(BaseModel):
    """Result payload for webhook registration calls."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    registered: bool
    detail: str


class SignalAdapterHealthResult(BaseModel):
    """Readiness payload for Signal adapter dependencies."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    adapter_ready: bool
    detail: str


class SignalAdapter(Protocol):
    """Protocol for Signal webhook registration and health checks."""

    def register_webhook(
        self,
        *,
        callback_url: str,
        shared_secret: str,
    ) -> SignalWebhookRegistrationResult:
        """Register callback URL and shared secret with Signal backend."""

    def health(self) -> SignalAdapterHealthResult:
        """Return adapter health state."""
