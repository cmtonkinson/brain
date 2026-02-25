"""Policy Service persistence repository implementations."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, desc, func, select, update
from sqlalchemy.dialects.postgresql import insert

from packages.brain_shared.ids import (
    generate_ulid_bytes,
    ulid_bytes_to_str,
    ulid_str_to_bytes,
)
from resources.substrates.postgres.schema_session import ServiceSchemaSessionProvider
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
from services.action.policy_service.data.schema import (
    active_policy_regime,
    approvals,
    policy_decisions,
    policy_dedupe_logs,
    policy_regimes,
)


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


class PostgresPolicyPersistenceRepository(PolicyPersistenceRepository):
    """SQL repository over Policy Service-owned schema tables."""

    def __init__(self, sessions: ServiceSchemaSessionProvider) -> None:
        self._sessions = sessions

    def upsert_policy_regime(
        self, *, snapshot: PolicyRegimeSnapshot
    ) -> PolicyRegimeSnapshot:
        regime_id_bytes = ulid_str_to_bytes(snapshot.policy_regime_id)
        with self._sessions.session() as session:
            stmt = insert(policy_regimes).values(
                id=regime_id_bytes,
                policy_hash=snapshot.policy_hash,
                policy_json=snapshot.policy_json,
                policy_id=snapshot.policy_id,
                policy_version=snapshot.policy_version,
                created_at=snapshot.created_at,
            )
            session.execute(stmt.on_conflict_do_nothing(index_elements=["policy_hash"]))
            row = (
                session.execute(
                    select(policy_regimes).where(
                        policy_regimes.c.policy_hash == snapshot.policy_hash
                    )
                )
                .mappings()
                .one()
            )
            return _to_regime_snapshot(row)

    def set_active_policy_regime(
        self, *, policy_regime_id: str
    ) -> ActivePolicyRegimePointer:
        regime_id_bytes = ulid_str_to_bytes(policy_regime_id)
        with self._sessions.session() as session:
            stmt = insert(active_policy_regime).values(
                id=generate_ulid_bytes(),
                pointer_id="active",
                policy_regime_id=regime_id_bytes,
            )
            session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["pointer_id"],
                    set_={"policy_regime_id": regime_id_bytes},
                )
            )
            return ActivePolicyRegimePointer(policy_regime_id=policy_regime_id)

    def get_active_policy_regime_id(self) -> str:
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(active_policy_regime.c.policy_regime_id).where(
                        active_policy_regime.c.pointer_id == "active"
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return ""
            return ulid_bytes_to_str(row["policy_regime_id"])

    def list_policy_regimes(self) -> tuple[PolicyRegimeSnapshot, ...]:
        with self._sessions.session() as session:
            rows = session.execute(select(policy_regimes)).mappings().all()
            return tuple(_to_regime_snapshot(row) for row in rows)

    def append_decision(self, *, row: PolicyDecisionLogRow) -> None:
        with self._sessions.session() as session:
            session.execute(
                insert(policy_decisions).values(
                    id=ulid_str_to_bytes(row.decision.decision_id),
                    policy_regime_id=ulid_str_to_bytes(row.decision.policy_regime_id),
                    envelope_id=row.metadata.envelope_id,
                    trace_id=row.metadata.trace_id,
                    actor=row.actor,
                    channel=row.channel,
                    capability_id=row.capability_id,
                    allowed=row.decision.allowed,
                    reason_codes=",".join(row.decision.reason_codes),
                    obligations=",".join(row.decision.obligations),
                    proposal_token=row.decision.policy_metadata.get(
                        "proposal_token", ""
                    ),
                    created_at=row.decision.decided_at,
                )
            )

    def append_proposal(self, *, row: PolicyApprovalProposalRow) -> None:
        with self._sessions.session() as session:
            stmt = insert(approvals).values(
                id=generate_ulid_bytes(),
                proposal_token=row.proposal.proposal_token,
                policy_regime_id=ulid_str_to_bytes(row.proposal.policy_regime_id),
                capability_id=row.proposal.capability_id,
                capability_version=row.proposal.capability_version,
                summary=row.proposal.summary,
                actor=row.proposal.actor,
                channel=row.proposal.channel,
                trace_id=row.proposal.trace_id,
                invocation_id=row.proposal.invocation_id,
                status=row.status,
                clarification_attempts=row.proposal.clarification_attempts,
                expires_at=row.proposal.expires_at,
                created_at=row.proposal.created_at,
            )
            session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["proposal_token"],
                    set_={
                        "status": row.status,
                        "capability_version": row.proposal.capability_version,
                        "summary": row.proposal.summary,
                        "trace_id": row.proposal.trace_id,
                        "invocation_id": row.proposal.invocation_id,
                        "clarification_attempts": row.proposal.clarification_attempts,
                        "expires_at": row.proposal.expires_at,
                    },
                )
            )

    def append_dedupe(self, *, row: PolicyDedupeLogRow) -> None:
        with self._sessions.session() as session:
            session.execute(
                insert(policy_dedupe_logs).values(
                    id=generate_ulid_bytes(),
                    dedupe_key=row.dedupe_key,
                    envelope_id=row.envelope_id,
                    trace_id=row.trace_id,
                    denied=row.denied,
                    window_seconds=row.window_seconds,
                    created_at=row.created_at,
                )
            )

    def find_pending_proposal(self, *, token: str) -> ApprovalProposal | None:
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(approvals)
                    .where(approvals.c.proposal_token == token)
                    .where(approvals.c.status == "pending")
                    .order_by(desc(approvals.c.created_at), desc(approvals.c.id))
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else _to_proposal(row)

    def list_pending_proposals(
        self, *, actor: str, channel: str
    ) -> tuple[PolicyApprovalProposalRow, ...]:
        with self._sessions.session() as session:
            rows = (
                session.execute(
                    select(approvals)
                    .where(approvals.c.status == "pending")
                    .where(approvals.c.actor == actor)
                    .where(approvals.c.channel == channel)
                    .order_by(approvals.c.created_at.asc(), approvals.c.id.asc())
                )
                .mappings()
                .all()
            )
            return tuple(
                PolicyApprovalProposalRow(proposal=_to_proposal(row), status="pending")
                for row in rows
            )

    def mark_proposal_status(self, *, token: str, status: str) -> None:
        with self._sessions.session() as session:
            session.execute(
                update(approvals)
                .where(approvals.c.proposal_token == token)
                .where(approvals.c.status == "pending")
                .values(status=status)
            )

    def increment_proposal_clarification_attempts(
        self, *, token: str
    ) -> ApprovalProposal | None:
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(approvals)
                    .where(approvals.c.proposal_token == token)
                    .where(approvals.c.status == "pending")
                    .order_by(desc(approvals.c.created_at), desc(approvals.c.id))
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            attempts = int(row["clarification_attempts"]) + 1
            session.execute(
                update(approvals)
                .where(approvals.c.proposal_token == token)
                .where(approvals.c.status == "pending")
                .values(clarification_attempts=attempts)
            )
            refreshed = (
                session.execute(
                    select(approvals)
                    .where(approvals.c.proposal_token == token)
                    .where(approvals.c.status == "pending")
                    .order_by(desc(approvals.c.created_at), desc(approvals.c.id))
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            return None if refreshed is None else _to_proposal(refreshed)

    def count_decisions(self) -> int:
        with self._sessions.session() as session:
            return int(
                session.scalar(select(func.count()).select_from(policy_decisions))
            )

    def count_proposals(self) -> int:
        with self._sessions.session() as session:
            return int(session.scalar(select(func.count()).select_from(approvals)))

    def count_dedupe(self) -> int:
        with self._sessions.session() as session:
            return int(
                session.scalar(select(func.count()).select_from(policy_dedupe_logs))
            )

    def trim_by_max_age(self, *, max_age_seconds: int) -> None:
        cutoff = utc_now() - timedelta(seconds=max_age_seconds)
        with self._sessions.session() as session:
            session.execute(
                delete(policy_decisions).where(policy_decisions.c.created_at < cutoff)
            )
            session.execute(delete(approvals).where(approvals.c.created_at < cutoff))
            session.execute(
                delete(policy_dedupe_logs).where(
                    policy_dedupe_logs.c.created_at < cutoff
                )
            )

    def trim_by_max_rows(self, *, max_rows: int) -> None:
        with self._sessions.session() as session:
            self._trim_table_by_rows(
                session=session,
                table=policy_decisions,
                max_rows=max_rows,
            )
            self._trim_table_by_rows(
                session=session,
                table=approvals,
                max_rows=max_rows,
            )
            self._trim_table_by_rows(
                session=session,
                table=policy_dedupe_logs,
                max_rows=max_rows,
            )

    def _trim_table_by_rows(self, *, session, table, max_rows: int) -> None:
        rows = (
            session.execute(
                select(table.c.id)
                .order_by(desc(table.c.created_at), desc(table.c.id))
                .offset(max_rows)
            )
            .scalars()
            .all()
        )
        if rows:
            session.execute(delete(table).where(table.c.id.in_(rows)))


def _to_regime_snapshot(row: dict[str, object]) -> PolicyRegimeSnapshot:
    return PolicyRegimeSnapshot(
        policy_regime_id=ulid_bytes_to_str(row["id"]),
        policy_hash=str(row["policy_hash"]),
        policy_json=str(row["policy_json"]),
        policy_id=str(row["policy_id"]),
        policy_version=str(row["policy_version"]),
        created_at=row["created_at"],
    )


def _to_proposal(row: dict[str, object]) -> ApprovalProposal:
    created_at = row["created_at"]
    return ApprovalProposal(
        proposal_token=str(row["proposal_token"]),
        capability_id=str(row["capability_id"]),
        capability_version=str(row["capability_version"]),
        summary=str(row["summary"]),
        actor=str(row["actor"]),
        channel=str(row["channel"]),
        trace_id=str(row["trace_id"]),
        invocation_id=str(row["invocation_id"]),
        policy_regime_id=ulid_bytes_to_str(row["policy_regime_id"]),
        created_at=created_at,
        expires_at=row["expires_at"],
        clarification_attempts=int(row["clarification_attempts"]),
    )
