"""Capability Engine audit repository implementations."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from packages.brain_shared.ids import generate_ulid_bytes
from resources.substrates.postgres.schema_session import ServiceSchemaSessionProvider
from services.action.capability_engine.domain import CapabilityInvocationAuditRow
from services.action.capability_engine.interfaces import (
    CapabilityInvocationAuditRepository,
)
from services.action.capability_engine.data.schema import invocation_audits


class InMemoryCapabilityInvocationAuditRepository(CapabilityInvocationAuditRepository):
    """Append-only in-memory invocation audit persistence for CES."""

    def __init__(self) -> None:
        self._rows: list[CapabilityInvocationAuditRow] = []

    def append(self, *, row: CapabilityInvocationAuditRow) -> None:
        """Persist one invocation audit row in append-only order."""
        self._rows.append(row)

    def count(self) -> int:
        """Return number of persisted invocation audit rows."""
        return len(self._rows)

    def list_rows(self) -> tuple[CapabilityInvocationAuditRow, ...]:
        """Expose immutable audit rows for tests and diagnostics."""
        return tuple(self._rows)


class PostgresCapabilityInvocationAuditRepository(CapabilityInvocationAuditRepository):
    """SQL repository over Capability Engine-owned invocation audit table."""

    def __init__(self, sessions: ServiceSchemaSessionProvider) -> None:
        self._sessions = sessions

    def append(self, *, row: CapabilityInvocationAuditRow) -> None:
        """Persist one invocation audit row."""
        with self._sessions.session() as session:
            session.execute(
                insert(invocation_audits).values(
                    id=generate_ulid_bytes(),
                    envelope_id=row.envelope_id,
                    trace_id=row.trace_id,
                    parent_id=row.parent_id,
                    invocation_id=row.invocation_id,
                    parent_invocation_id=row.parent_invocation_id,
                    actor=row.actor,
                    source=row.source,
                    channel=row.channel,
                    capability_id=row.capability_id,
                    capability_version=row.capability_version,
                    policy_decision_id=row.policy_decision_id,
                    policy_regime_id=row.policy_regime_id,
                    allowed=row.allowed,
                    reason_codes=",".join(row.reason_codes),
                    proposal_token=row.proposal_token,
                    created_at=row.created_at,
                )
            )

    def count(self) -> int:
        """Return total persisted invocation audit row count."""
        with self._sessions.session() as session:
            return int(
                session.scalar(select(func.count()).select_from(invocation_audits))
            )
