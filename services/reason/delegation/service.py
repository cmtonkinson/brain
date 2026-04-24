"""Authoritative in-process Python API for Delegation Service."""

from __future__ import annotations

from abc import ABC, abstractmethod

from lib.shared.config import CoreRuntimeSettings
from lib.shared.envelope import Envelope, EnvelopeMeta
from services.effect.language.service import LanguageService
from services.reason.delegation.domain import (
    CancelOutcome,
    CancelReason,
    ClaimedInvocation,
    HealthStatus,
    InvocationResult,
    InvocationStarted,
    InvocationStatus,
    InvocationStatusView,
    TurnDecision,
)


class DelegationService(ABC):
    """Public API for the Delegation Service."""

    @abstractmethod
    def invoke(
        self,
        *,
        meta: EnvelopeMeta,
        prompt: str,
        context_text: str | None = None,
        context_object_refs: tuple[str, ...] = (),
        personality_id: str = "subagent",
        tool_allowlist: tuple[str, ...] | None = None,
        max_turns: int = 8,
        budget_tokens: int | None = None,
        max_wallclock_seconds: int | None = None,
        parent_invocation_id: str | None = None,
    ) -> Envelope[InvocationStarted]:
        """Queue one delegated invocation for asynchronous execution."""

    @abstractmethod
    def invoke_and_wait(
        self,
        *,
        meta: EnvelopeMeta,
        prompt: str,
        context_text: str | None = None,
        context_object_refs: tuple[str, ...] = (),
        personality_id: str = "subagent",
        tool_allowlist: tuple[str, ...] | None = None,
        max_turns: int = 8,
        budget_tokens: int | None = None,
        max_wallclock_seconds: int | None = None,
        parent_invocation_id: str | None = None,
        timeout_seconds: float | None = None,
    ) -> Envelope[InvocationResult]:
        """Queue one delegated invocation and block until terminal state."""

    @abstractmethod
    def wait(
        self,
        *,
        meta: EnvelopeMeta,
        invocation_id: str,
        timeout_seconds: float | None = None,
    ) -> Envelope[InvocationResult]:
        """Block until the named invocation reaches terminal state."""

    @abstractmethod
    def get_status(
        self,
        *,
        meta: EnvelopeMeta,
        invocation_id: str,
    ) -> Envelope[InvocationStatusView]:
        """Return the current status projection for one invocation."""

    @abstractmethod
    def cancel(
        self,
        *,
        meta: EnvelopeMeta,
        invocation_id: str,
        reason: CancelReason = CancelReason.manual,
    ) -> Envelope[CancelOutcome]:
        """Request cancellation of one running or queued invocation."""

    @abstractmethod
    def claim_next_invocation(
        self,
        *,
        meta: EnvelopeMeta,
        claimed_by: str,
    ) -> Envelope[ClaimedInvocation | None]:
        """Atomic-claim the next queued invocation for a Subagent Actor."""

    @abstractmethod
    def record_turn(
        self,
        *,
        meta: EnvelopeMeta,
        invocation_id: str,
    ) -> Envelope[TurnDecision]:
        """Bump turn count, refresh token totals from the audit trail, and
        return whether to continue.

        Token totals come from the Language Service's audit aggregation
        (``get_token_usage_by_trace``) rather than caller-supplied deltas;
        the audit is the source of truth for actual provider spend.
        """

    @abstractmethod
    def finalize_invocation(
        self,
        *,
        meta: EnvelopeMeta,
        invocation_id: str,
        status: InvocationStatus,
        final_response: str | None = None,
        transcript_ref: str | None = None,
        cancel_reason: CancelReason | None = None,
    ) -> Envelope[InvocationResult]:
        """Apply terminal status to an invocation and unblock waiters."""

    @abstractmethod
    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        """Return Delegation Service and Postgres substrate readiness."""


def build_delegation_service(
    *,
    settings: CoreRuntimeSettings,
    language_model: LanguageService,
) -> DelegationService:
    """Build the default Delegation implementation from typed settings."""
    from services.reason.delegation.implementation import DefaultDelegationService

    return DefaultDelegationService.from_settings(
        settings=settings, language_model=language_model
    )


__all__ = [
    "CancelOutcome",
    "CancelReason",
    "ClaimedInvocation",
    "DelegationService",
    "HealthStatus",
    "InvocationResult",
    "InvocationStarted",
    "InvocationStatus",
    "InvocationStatusView",
    "TurnDecision",
    "build_delegation_service",
]
