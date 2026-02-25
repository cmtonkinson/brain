"""Transport-neutral protocol interfaces for Policy Service persistence."""

from __future__ import annotations

from typing import Protocol

from services.action.policy_service.domain import (
    ActivePolicyRegimePointer,
    ApprovalProposal,
    PolicyApprovalProposalRow,
    PolicyDecisionLogRow,
    PolicyDedupeLogRow,
    PolicyRegimeSnapshot,
)


class PolicyPersistenceRepository(Protocol):
    """Protocol for append-only policy regime/decision/approval persistence."""

    def upsert_policy_regime(
        self, *, snapshot: PolicyRegimeSnapshot
    ) -> PolicyRegimeSnapshot:
        """Insert one policy regime by hash or return existing row."""

    def set_active_policy_regime(
        self, *, policy_regime_id: str
    ) -> ActivePolicyRegimePointer:
        """Set and return active policy regime pointer."""

    def get_active_policy_regime_id(self) -> str:
        """Read active policy regime identifier."""

    def list_policy_regimes(self) -> tuple[PolicyRegimeSnapshot, ...]:
        """Return all known policy regimes."""

    def append_decision(self, *, row: PolicyDecisionLogRow) -> None:
        """Persist one policy decision audit row."""

    def append_proposal(self, *, row: PolicyApprovalProposalRow) -> None:
        """Persist one approval proposal audit row."""

    def append_dedupe(self, *, row: PolicyDedupeLogRow) -> None:
        """Persist one dedupe check audit row."""

    def find_pending_proposal(self, *, token: str) -> ApprovalProposal | None:
        """Resolve one pending proposal by token."""

    def list_pending_proposals(
        self, *, actor: str, channel: str
    ) -> tuple[PolicyApprovalProposalRow, ...]:
        """List pending proposals for one actor/channel pair."""

    def mark_proposal_status(self, *, token: str, status: str) -> None:
        """Update one pending proposal state."""

    def increment_proposal_clarification_attempts(
        self, *, token: str
    ) -> ApprovalProposal | None:
        """Increment clarification attempts and return updated proposal."""

    def count_decisions(self) -> int:
        """Return number of decision rows."""

    def count_proposals(self) -> int:
        """Return number of proposal rows."""

    def count_dedupe(self) -> int:
        """Return number of dedupe rows."""

    def trim_by_max_age(self, *, max_age_seconds: int) -> None:
        """Apply age-based retention to append-only logs."""

    def trim_by_max_rows(self, *, max_rows: int) -> None:
        """Apply row-count retention to append-only logs."""
