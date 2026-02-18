"""Repository helpers for EAS-owned Postgres records."""

from __future__ import annotations

from sqlalchemy import insert, select

from packages.brain_shared.envelope import EnvelopeMeta
from packages.brain_shared.ids import generate_ulid_bytes
from resources.substrates.postgres.schema_session import ServiceSchemaSessionProvider
from services.state.embedding_authority.data.mappers import row_to_audit_entry
from services.state.embedding_authority.data.schema import embedding_audit_log
from services.state.embedding_authority.data.types import EmbeddingAuditEntry
from services.state.embedding_authority.domain import EmbeddingRef


class EmbeddingAuditRepository:
    """Persist and query EAS-local audit records in the owned schema."""

    def __init__(self, sessions: ServiceSchemaSessionProvider) -> None:
        self._sessions = sessions

    def record_operation(
        self,
        *,
        meta: EnvelopeMeta,
        operation: str,
        ref: EmbeddingRef,
        model: str,
        outcome: str,
        error_code: str = "",
    ) -> None:
        """Insert one audit record representing a completed EAS operation."""
        with self._sessions.session() as session:
            session.execute(
                insert(embedding_audit_log).values(
                    id=generate_ulid_bytes(),
                    envelope_id=meta.envelope_id,
                    trace_id=meta.trace_id,
                    principal=meta.principal,
                    operation=operation,
                    namespace=ref.namespace,
                    key=ref.key,
                    model=model,
                    outcome=outcome,
                    error_code=error_code,
                )
            )

    def list_recent(self, *, limit: int = 100) -> list[EmbeddingAuditEntry]:
        """Return most-recent EAS audit entries in descending time order."""
        bounded_limit = 1 if limit <= 0 else min(limit, 1000)
        with self._sessions.session() as session:
            rows = session.execute(
                select(embedding_audit_log)
                .order_by(embedding_audit_log.c.occurred_at.desc(), embedding_audit_log.c.id.desc())
                .limit(bounded_limit)
            ).mappings().all()
            return [row_to_audit_entry(row) for row in rows]
