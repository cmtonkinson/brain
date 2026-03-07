"""Append-only provider call audit repository for Language Model Service."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from packages.brain_shared.ids import generate_ulid_bytes
from resources.substrates.postgres.schema_session import ServiceSchemaSessionProvider
from services.action.language_model.data.schema import call_audits
from services.action.language_model.domain import LanguageModelCallAuditRow
from services.action.language_model.interfaces import LanguageModelCallAuditRepository


class InMemoryLanguageModelCallAuditRepository(LanguageModelCallAuditRepository):
    """Append-only in-memory provider call audit repository for LMS."""

    def __init__(self) -> None:
        self._rows: list[LanguageModelCallAuditRow] = []

    def append(self, *, row: LanguageModelCallAuditRow) -> LanguageModelCallAuditRow:
        """Persist one provider call audit row in append-only order."""
        self._rows.append(row)
        return row

    def next_call_index(self, *, trace_id: str) -> int:
        """Return the next append-only call index for one trace."""
        return 1 + sum(1 for row in self._rows if row.trace_id == trace_id)

    def count(self) -> int:
        """Return total persisted provider call audit row count."""
        return len(self._rows)

    def list_rows(self) -> tuple[LanguageModelCallAuditRow, ...]:
        """Expose immutable audit rows for tests and diagnostics."""
        return tuple(self._rows)


class PostgresLanguageModelCallAuditRepository(LanguageModelCallAuditRepository):
    """SQL repository over LMS-owned provider call audit table."""

    def __init__(self, sessions: ServiceSchemaSessionProvider) -> None:
        self._sessions = sessions

    def append(self, *, row: LanguageModelCallAuditRow) -> LanguageModelCallAuditRow:
        """Persist one provider call audit row."""
        with self._sessions.session() as session:
            session.execute(
                insert(call_audits).values(
                    id=generate_ulid_bytes(),
                    envelope_id=row.envelope_id,
                    trace_id=row.trace_id,
                    parent_id=row.parent_id,
                    source=row.source,
                    principal=row.principal,
                    provider=row.provider,
                    model=row.model,
                    profile=row.profile,
                    operation=row.operation,
                    request_phase=row.request_phase,
                    outcome_kind=row.outcome_kind,
                    call_index=row.call_index,
                    duration_ms=row.duration_ms,
                    finish_reason=row.finish_reason,
                    error_message=row.error_message,
                    request_json=row.request_json,
                    response_json=row.response_json,
                    created_at=row.created_at,
                )
            )
        return row

    def next_call_index(self, *, trace_id: str) -> int:
        """Return the next append-only call index for one trace."""
        with self._sessions.session() as session:
            current = session.scalar(
                select(func.max(call_audits.c.call_index)).where(
                    call_audits.c.trace_id == trace_id
                )
            )
            return 1 if current is None else int(current) + 1

    def count(self) -> int:
        """Return total persisted provider call audit row count."""
        with self._sessions.session() as session:
            return int(session.scalar(select(func.count()).select_from(call_audits)))
