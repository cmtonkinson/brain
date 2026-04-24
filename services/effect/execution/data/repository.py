"""Execution repository implementations."""

from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from lib.shared.ids import generate_ulid_bytes
from resources.substrates.postgres.schema_session import ServiceSchemaSessionProvider
from services.effect.execution.domain import (
    DynamicOpClassificationRow,
    OpDiscoveryStateRow,
    OpInvocationAuditRow,
)
from services.effect.execution.interfaces import (
    DynamicOpClassificationRepository,
    OpDiscoveryStateRepository,
    OpInvocationAuditRepository,
)
from services.effect.execution.data.schema import (
    dynamic_op_classifications,
    op_discovery_state,
    invocation_audits,
)


class InMemoryOpInvocationAuditRepository(OpInvocationAuditRepository):
    """Append-only in-memory invocation audit persistence for Execution."""

    def __init__(self) -> None:
        self._rows: list[OpInvocationAuditRow] = []

    def append(self, *, row: OpInvocationAuditRow) -> None:
        """Persist one invocation audit row in append-only order."""
        self._rows.append(row)

    def count(self) -> int:
        """Return number of persisted invocation audit rows."""
        return len(self._rows)

    def list_rows(self) -> tuple[OpInvocationAuditRow, ...]:
        """Expose immutable audit rows for tests and diagnostics."""
        return tuple(self._rows)


class InMemoryOpDiscoveryStateRepository(OpDiscoveryStateRepository):
    """In-memory durable-state test double for Execution op discovery state."""

    def __init__(self) -> None:
        self._rows: dict[str, OpDiscoveryStateRow] = {}

    def list_rows(self) -> tuple[OpDiscoveryStateRow, ...]:
        """Return all persisted rows sorted by op id."""
        return tuple(self._rows[key] for key in sorted(self._rows))

    def upsert(self, *, row: OpDiscoveryStateRow) -> None:
        """Persist or replace one discovery-state row."""
        self._rows[row.op_id] = row

    def delete(self, *, op_id: str) -> None:
        """Delete one discovery-state row if it exists."""
        self._rows.pop(op_id, None)


class InMemoryDynamicOpClassificationRepository(DynamicOpClassificationRepository):
    """In-memory persisted observed-definition and classification state."""

    def __init__(self) -> None:
        self._rows: dict[str, DynamicOpClassificationRow] = {}

    def list_rows(self) -> tuple[DynamicOpClassificationRow, ...]:
        """Return all rows sorted by op id."""
        return tuple(self._rows[key] for key in sorted(self._rows))

    def get(self, *, op_id: str) -> DynamicOpClassificationRow | None:
        """Return one row by op id."""
        return self._rows.get(op_id)

    def upsert_observed(
        self, *, row: DynamicOpClassificationRow
    ) -> DynamicOpClassificationRow:
        """Persist latest observed definition and clear stale classifications."""
        existing = self._rows.get(row.op_id)
        if existing is not None and existing.definition_digest == row.definition_digest:
            if existing.effect is not None and existing.approval is not None:
                return existing
        self._rows[row.op_id] = row
        return row

    def classify(
        self,
        *,
        op_id: str,
        definition_digest: str,
        effect: str | None = None,
        approval: str | None = None,
    ) -> DynamicOpClassificationRow:
        """Persist operator classification for one observed dynamic op."""
        if effect is None and approval is None:
            raise ValueError("classify requires at least one of effect or approval")
        existing = self._rows.get(op_id)
        if existing is None or existing.definition_digest != definition_digest:
            raise KeyError(op_id)
        updates: dict[str, str] = {}
        if effect is not None:
            updates["effect"] = effect
        if approval is not None:
            updates["approval"] = approval
        updated = existing.model_copy(update=updates)
        self._rows[op_id] = updated
        return updated


class PostgresOpInvocationAuditRepository(OpInvocationAuditRepository):
    """SQL repository over Execution-owned invocation audit table."""

    def __init__(self, sessions: ServiceSchemaSessionProvider) -> None:
        self._sessions = sessions

    def append(self, *, row: OpInvocationAuditRow) -> None:
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
                    op_id=row.op_id,
                    op_version=row.op_version,
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


class PostgresOpDiscoveryStateRepository(OpDiscoveryStateRepository):
    """SQL repository over Execution-owned op discovery state."""

    def __init__(self, sessions: ServiceSchemaSessionProvider) -> None:
        self._sessions = sessions

    def list_rows(self) -> tuple[OpDiscoveryStateRow, ...]:
        """Return all persisted rows sorted by op id."""
        with self._sessions.session() as session:
            rows = (
                session.execute(
                    select(op_discovery_state).order_by(
                        op_discovery_state.c.op_id.asc()
                    )
                )
                .mappings()
                .all()
            )
            return tuple(
                OpDiscoveryStateRow(
                    op_id=str(row["op_id"]),
                    content_digest=str(row["content_digest"]),
                    chunk_ordinal=int(row["chunk_ordinal"]),
                )
                for row in rows
            )

    def upsert(self, *, row: OpDiscoveryStateRow) -> None:
        """Persist or replace one discovery-state row."""
        with self._sessions.session() as session:
            stmt = insert(op_discovery_state).values(
                id=generate_ulid_bytes(),
                op_id=row.op_id,
                content_digest=row.content_digest,
                chunk_ordinal=row.chunk_ordinal,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[op_discovery_state.c.op_id],
                set_={
                    "content_digest": row.content_digest,
                    "chunk_ordinal": row.chunk_ordinal,
                    "updated_at": func.now(),
                },
            )
            session.execute(stmt)

    def delete(self, *, op_id: str) -> None:
        """Delete one discovery-state row by op id."""
        with self._sessions.session() as session:
            session.execute(
                op_discovery_state.delete().where(op_discovery_state.c.op_id == op_id)
            )


class PostgresDynamicOpClassificationRepository(DynamicOpClassificationRepository):
    """SQL repository over Execution-owned dynamic-op classifications."""

    def __init__(self, sessions: ServiceSchemaSessionProvider) -> None:
        self._sessions = sessions

    def list_rows(self) -> tuple[DynamicOpClassificationRow, ...]:
        """Return all persisted rows sorted by op id."""
        with self._sessions.session() as session:
            rows = (
                session.execute(
                    select(dynamic_op_classifications).order_by(
                        dynamic_op_classifications.c.op_id.asc()
                    )
                )
                .mappings()
                .all()
            )
            return tuple(self._row_from_mapping(row) for row in rows)

    def get(self, *, op_id: str) -> DynamicOpClassificationRow | None:
        """Return one persisted row by op id."""
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(dynamic_op_classifications).where(
                        dynamic_op_classifications.c.op_id == op_id
                    )
                )
                .mappings()
                .first()
            )
            return None if row is None else self._row_from_mapping(row)

    def upsert_observed(
        self, *, row: DynamicOpClassificationRow
    ) -> DynamicOpClassificationRow:
        """Persist latest observed definition and clear stale classifications."""
        existing = self.get(op_id=row.op_id)
        effect = row.effect
        approval = row.approval
        if existing is not None and existing.definition_digest == row.definition_digest:
            if existing.effect is not None and existing.approval is not None:
                effect = existing.effect
                approval = existing.approval
        with self._sessions.session() as session:
            stmt = insert(dynamic_op_classifications).values(
                id=generate_ulid_bytes(),
                op_id=row.op_id,
                source_kind=row.source_kind,
                source_ref=row.source_ref,
                definition_digest=row.definition_digest,
                summary=row.summary,
                input_schema_json=(
                    None
                    if row.input_schema is None
                    else json.dumps(row.input_schema, sort_keys=True)
                ),
                output_schema_json=(
                    None
                    if row.output_schema is None
                    else json.dumps(row.output_schema, sort_keys=True)
                ),
                effect=effect,
                approval=approval,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[dynamic_op_classifications.c.op_id],
                set_={
                    "source_kind": row.source_kind,
                    "source_ref": row.source_ref,
                    "definition_digest": row.definition_digest,
                    "summary": row.summary,
                    "input_schema_json": (
                        None
                        if row.input_schema is None
                        else json.dumps(row.input_schema, sort_keys=True)
                    ),
                    "output_schema_json": (
                        None
                        if row.output_schema is None
                        else json.dumps(row.output_schema, sort_keys=True)
                    ),
                    "effect": effect,
                    "approval": approval,
                    "updated_at": func.now(),
                },
            )
            session.execute(stmt)
        persisted = self.get(op_id=row.op_id)
        if persisted is None:
            raise RuntimeError("dynamic op classification upsert did not persist")
        return persisted

    def classify(
        self,
        *,
        op_id: str,
        definition_digest: str,
        effect: str | None = None,
        approval: str | None = None,
    ) -> DynamicOpClassificationRow:
        """Persist operator classification for one observed dynamic op."""
        if effect is None and approval is None:
            raise ValueError("classify requires at least one of effect or approval")
        existing = self.get(op_id=op_id)
        if existing is None or existing.definition_digest != definition_digest:
            raise KeyError(op_id)
        values: dict[str, object] = {"updated_at": func.now()}
        if effect is not None:
            values["effect"] = effect
        if approval is not None:
            values["approval"] = approval
        with self._sessions.session() as session:
            stmt = (
                dynamic_op_classifications.update()
                .where(dynamic_op_classifications.c.op_id == op_id)
                .values(**values)
            )
            session.execute(stmt)
        persisted = self.get(op_id=op_id)
        if persisted is None:
            raise RuntimeError("dynamic op classification update did not persist")
        return persisted

    def _row_from_mapping(self, row) -> DynamicOpClassificationRow:
        """Convert one SQL row mapping into the typed domain model."""
        return DynamicOpClassificationRow(
            op_id=str(row["op_id"]),
            source_kind=str(row["source_kind"]),
            source_ref=str(row["source_ref"]),
            definition_digest=str(row["definition_digest"]),
            summary=str(row["summary"]),
            input_schema=(
                None
                if row["input_schema_json"] is None
                else json.loads(str(row["input_schema_json"]))
            ),
            output_schema=(
                None
                if row["output_schema_json"] is None
                else json.loads(str(row["output_schema_json"]))
            ),
            effect=None if row["effect"] is None else str(row["effect"]),
            approval=None if row["approval"] is None else str(row["approval"]),
        )
