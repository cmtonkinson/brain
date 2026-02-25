"""Policy Service persistence repository implementations."""

from __future__ import annotations

from datetime import timedelta

from services.action.policy_service.domain import (
    ActivePolicyRegimePointer,
    ApprovalProposal,
    PolicyApprovalProposalRow,
    PolicyDecisionLogRow,
    PolicyDedupeLogRow,
    PolicyRegimeSnapshot,
    utc_now,
)
from services.action.policy_service.interfaces import PolicyPersistenceRepository


class InMemoryPolicyPersistenceRepository(PolicyPersistenceRepository):
    """Append-only in-memory repository for Policy Service durable contracts."""

    def __init__(self) -> None:
        self._regimes_by_hash: dict[str, PolicyRegimeSnapshot] = {}
        self._active_pointer: ActivePolicyRegimePointer | None = None
        self._decision_rows: list[PolicyDecisionLogRow] = []
        self._proposal_rows: list[PolicyApprovalProposalRow] = []
        self._dedupe_rows: list[PolicyDedupeLogRow] = []

    def upsert_policy_regime(
        self, *, snapshot: PolicyRegimeSnapshot
    ) -> PolicyRegimeSnapshot:
        existing = self._regimes_by_hash.get(snapshot.policy_hash)
        if existing is not None:
            return existing
        self._regimes_by_hash[snapshot.policy_hash] = snapshot
        return snapshot

    def set_active_policy_regime(
        self, *, policy_regime_id: str
    ) -> ActivePolicyRegimePointer:
        self._active_pointer = ActivePolicyRegimePointer(
            policy_regime_id=policy_regime_id
        )
        return self._active_pointer

    def get_active_policy_regime_id(self) -> str:
        if self._active_pointer is None:
            return ""
        return self._active_pointer.policy_regime_id

    def list_policy_regimes(self) -> tuple[PolicyRegimeSnapshot, ...]:
        return tuple(self._regimes_by_hash.values())

    def append_decision(self, *, row: PolicyDecisionLogRow) -> None:
        self._decision_rows.append(row)

    def append_proposal(self, *, row: PolicyApprovalProposalRow) -> None:
        self._proposal_rows.append(row)

    def append_dedupe(self, *, row: PolicyDedupeLogRow) -> None:
        self._dedupe_rows.append(row)

    def find_pending_proposal(self, *, token: str) -> ApprovalProposal | None:
        for row in reversed(self._proposal_rows):
            if row.proposal.proposal_token == token and row.status == "pending":
                return row.proposal
        return None

    def list_pending_proposals(
        self, *, actor: str, channel: str
    ) -> tuple[PolicyApprovalProposalRow, ...]:
        return tuple(
            row
            for row in self._proposal_rows
            if row.status == "pending"
            and row.proposal.actor == actor
            and row.proposal.channel == channel
        )

    def mark_proposal_status(self, *, token: str, status: str) -> None:
        for index in range(len(self._proposal_rows) - 1, -1, -1):
            row = self._proposal_rows[index]
            if row.proposal.proposal_token == token and row.status == "pending":
                self._proposal_rows[index] = row.model_copy(update={"status": status})
                return

    def increment_proposal_clarification_attempts(
        self, *, token: str
    ) -> ApprovalProposal | None:
        for index in range(len(self._proposal_rows) - 1, -1, -1):
            row = self._proposal_rows[index]
            if row.proposal.proposal_token == token and row.status == "pending":
                proposal = row.proposal.model_copy(
                    update={
                        "clarification_attempts": row.proposal.clarification_attempts
                        + 1
                    }
                )
                self._proposal_rows[index] = row.model_copy(
                    update={"proposal": proposal}
                )
                return proposal
        return None

    def count_decisions(self) -> int:
        return len(self._decision_rows)

    def count_proposals(self) -> int:
        return len(self._proposal_rows)

    def count_dedupe(self) -> int:
        return len(self._dedupe_rows)

    def trim_by_max_age(self, *, max_age_seconds: int) -> None:
        cutoff = utc_now() - timedelta(seconds=max_age_seconds)
        self._decision_rows = [
            row for row in self._decision_rows if row.decision.decided_at >= cutoff
        ]
        self._proposal_rows = [
            row for row in self._proposal_rows if row.proposal.created_at >= cutoff
        ]
        self._dedupe_rows = [
            row for row in self._dedupe_rows if row.created_at >= cutoff
        ]

    def trim_by_max_rows(self, *, max_rows: int) -> None:
        self._decision_rows = self._decision_rows[-max_rows:]
        self._proposal_rows = self._proposal_rows[-max_rows:]
        self._dedupe_rows = self._dedupe_rows[-max_rows:]
