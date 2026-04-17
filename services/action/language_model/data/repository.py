"""Append-only provider call audit repository for Language Model Service."""

from __future__ import annotations

from sqlalchemy import desc, func, select
from sqlalchemy.dialects.postgresql import insert

from packages.brain_shared.ids import generate_ulid_bytes
from resources.substrates.postgres.schema_session import ServiceSchemaSessionProvider
from services.action.language_model.data.schema import call_audits, turn_cache_hops
from services.action.language_model.domain import (
    LanguageModelCallAuditRow,
    LanguageModelTurnCacheHopRow,
)
from services.action.language_model.interfaces import (
    LanguageModelCallAuditRepository,
    LanguageModelTurnCacheHopRepository,
)


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


class InMemoryLanguageModelTurnCacheHopRepository(LanguageModelTurnCacheHopRepository):
    """Append-only in-memory per-hop cache telemetry repository for LMS."""

    def __init__(self) -> None:
        self._rows: list[LanguageModelTurnCacheHopRow] = []

    def append(
        self, *, row: LanguageModelTurnCacheHopRow
    ) -> LanguageModelTurnCacheHopRow:
        """Persist one per-hop cache telemetry row in append-only order."""
        self._rows.append(row)
        return row

    def next_hop_ordinal(self, *, trace_id: str) -> int:
        """Return the next chat-with-tools hop ordinal for one trace."""
        return 1 + sum(1 for row in self._rows if row.trace_id == trace_id)

    def list_rows(self) -> tuple[LanguageModelTurnCacheHopRow, ...]:
        """Expose immutable per-hop telemetry rows for tests and diagnostics."""
        return tuple(self._rows)


class PostgresLanguageModelTurnCacheHopRepository(LanguageModelTurnCacheHopRepository):
    """SQL repository over LMS-owned per-hop cache telemetry table."""

    def __init__(self, sessions: ServiceSchemaSessionProvider) -> None:
        self._sessions = sessions

    def append(
        self, *, row: LanguageModelTurnCacheHopRow
    ) -> LanguageModelTurnCacheHopRow:
        """Persist one per-hop cache telemetry row."""
        with self._sessions.session() as session:
            session.execute(
                insert(turn_cache_hops).values(
                    id=generate_ulid_bytes(),
                    trace_id=row.trace_id,
                    hop_ordinal=row.hop_ordinal,
                    call_index=row.call_index,
                    envelope_id=row.envelope_id,
                    provider=row.provider,
                    model=row.model,
                    profile=row.profile,
                    placed_cachepoint_ordinal=row.placed_cachepoint_ordinal,
                    cp0_active=row.cp0_active,
                    cp1_active=row.cp1_active,
                    cp2_active=row.cp2_active,
                    cp3_active=row.cp3_active,
                    active_cachepoint_count=row.active_cachepoint_count,
                    provider_cache_control_block_count=row.provider_cache_control_block_count,
                    cache_creation_input_tokens=row.cache_creation_input_tokens,
                    cache_read_input_tokens=row.cache_read_input_tokens,
                    estimated_write_premium_token_equiv=row.estimated_write_premium_token_equiv,
                    estimated_read_savings_token_equiv=row.estimated_read_savings_token_equiv,
                    estimated_net_token_equiv=row.estimated_net_token_equiv,
                    created_at=row.created_at,
                )
            )
        return row

    def next_hop_ordinal(self, *, trace_id: str) -> int:
        """Return the next chat-with-tools hop ordinal for one trace."""
        with self._sessions.session() as session:
            current = session.scalar(
                select(func.max(turn_cache_hops.c.hop_ordinal)).where(
                    turn_cache_hops.c.trace_id == trace_id
                )
            )
            return 1 if current is None else int(current) + 1

    def list_rows(self) -> tuple[LanguageModelTurnCacheHopRow, ...]:
        """Expose immutable per-hop telemetry rows for tests and diagnostics."""
        with self._sessions.session() as session:
            rows = session.execute(
                select(turn_cache_hops).order_by(
                    turn_cache_hops.c.trace_id.asc(),
                    turn_cache_hops.c.hop_ordinal.asc(),
                    desc(turn_cache_hops.c.created_at),
                )
            ).mappings()
            return tuple(
                LanguageModelTurnCacheHopRow.model_validate(
                    {key: value for key, value in dict(row).items() if key != "id"}
                )
                for row in rows
            )
