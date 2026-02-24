"""Authoritative Postgres repository for Memory Authority Service state."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import desc, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from packages.brain_shared.ids import (
    generate_ulid_bytes,
    ulid_bytes_to_str,
    ulid_str_to_bytes,
)
from resources.substrates.postgres.schema_session import ServiceSchemaSessionProvider
from services.state.memory_authority.domain import (
    SessionRecord,
    TurnDirection,
    TurnRecord,
    TurnSummaryRecord,
)

from .schema import sessions, turn_summaries, turns


class MemoryRepository(Protocol):
    """Protocol for MAS authoritative persistence operations."""

    def create_session(self) -> SessionRecord:
        """Create and return one session row."""

    def get_session(self, *, session_id: str) -> SessionRecord | None:
        """Read one session by id."""

    def update_focus(
        self,
        *,
        session_id: str,
        focus: str | None,
        focus_token_count: int | None,
    ) -> SessionRecord | None:
        """Update focus fields for one session and return latest row."""

    def clear_session(
        self,
        *,
        session_id: str,
        dialogue_start_turn_id: str | None,
    ) -> SessionRecord | None:
        """Advance dialogue pointer and clear focus fields for one session."""

    def insert_turn(
        self,
        *,
        session_id: str,
        direction: TurnDirection,
        content: str,
        role: str,
        model: str | None,
        provider: str | None,
        token_count: int | None,
        reasoning_level: str | None,
        trace_id: str,
        principal: str,
    ) -> TurnRecord:
        """Insert one dialogue turn row and return it."""

    def list_turns(self, *, session_id: str) -> list[TurnRecord]:
        """List dialogue turns ordered by creation time."""

    def get_latest_turn(self, *, session_id: str) -> TurnRecord | None:
        """Read latest turn for one session."""

    def list_turn_summaries(self, *, session_id: str) -> list[TurnSummaryRecord]:
        """List persisted turn summaries for one session."""

    def get_turn_summary_by_range(
        self,
        *,
        session_id: str,
        start_turn_id: str,
        end_turn_id: str,
    ) -> TurnSummaryRecord | None:
        """Read one summary row by exact turn range."""

    def create_turn_summary(
        self,
        *,
        session_id: str,
        start_turn_id: str,
        end_turn_id: str,
        content: str,
        token_count: int,
    ) -> TurnSummaryRecord:
        """Create summary row for one turn range and return persisted value."""


class PostgresMemoryRepository:
    """SQL repository over MAS-owned schema tables."""

    def __init__(self, sessions_provider: ServiceSchemaSessionProvider) -> None:
        self._sessions = sessions_provider

    def create_session(self) -> SessionRecord:
        """Create and return one new session row."""
        session_id = generate_ulid_bytes()
        with self._sessions.session() as session:
            session.execute(
                insert(sessions).values(
                    id=session_id,
                    focus=None,
                    focus_token_count=None,
                    dialogue_start_turn_id=None,
                )
            )
            row = (
                session.execute(select(sessions).where(sessions.c.id == session_id))
                .mappings()
                .one()
            )
            return _to_session(row)

    def get_session(self, *, session_id: str) -> SessionRecord | None:
        """Read one session row by id."""
        session_id_bytes = ulid_str_to_bytes(session_id)
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(sessions).where(sessions.c.id == session_id_bytes)
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else _to_session(row)

    def update_focus(
        self,
        *,
        session_id: str,
        focus: str | None,
        focus_token_count: int | None,
    ) -> SessionRecord | None:
        """Update focus fields for one session and return latest session row."""
        session_id_bytes = ulid_str_to_bytes(session_id)
        with self._sessions.session() as session:
            result = session.execute(
                update(sessions)
                .where(sessions.c.id == session_id_bytes)
                .values(
                    focus=focus,
                    focus_token_count=focus_token_count,
                    updated_at=datetime.now(UTC),
                )
            )
            if int(result.rowcount or 0) == 0:
                return None
            row = (
                session.execute(
                    select(sessions).where(sessions.c.id == session_id_bytes)
                )
                .mappings()
                .one()
            )
            return _to_session(row)

    def clear_session(
        self,
        *,
        session_id: str,
        dialogue_start_turn_id: str | None,
    ) -> SessionRecord | None:
        """Advance pointer and clear focus fields for one session."""
        session_id_bytes = ulid_str_to_bytes(session_id)
        pointer = (
            None
            if dialogue_start_turn_id is None
            else ulid_str_to_bytes(dialogue_start_turn_id)
        )
        with self._sessions.session() as session:
            result = session.execute(
                update(sessions)
                .where(sessions.c.id == session_id_bytes)
                .values(
                    dialogue_start_turn_id=pointer,
                    focus=None,
                    focus_token_count=None,
                    updated_at=datetime.now(UTC),
                )
            )
            if int(result.rowcount or 0) == 0:
                return None
            row = (
                session.execute(
                    select(sessions).where(sessions.c.id == session_id_bytes)
                )
                .mappings()
                .one()
            )
            return _to_session(row)

    def insert_turn(
        self,
        *,
        session_id: str,
        direction: TurnDirection,
        content: str,
        role: str,
        model: str | None,
        provider: str | None,
        token_count: int | None,
        reasoning_level: str | None,
        trace_id: str,
        principal: str,
    ) -> TurnRecord:
        """Insert one turn row and return mapped domain record."""
        turn_id = generate_ulid_bytes()
        session_id_bytes = ulid_str_to_bytes(session_id)
        with self._sessions.session() as session:
            session.execute(
                insert(turns).values(
                    id=turn_id,
                    session_id=session_id_bytes,
                    direction=direction.value,
                    content=content,
                    role=role,
                    model=model,
                    provider=provider,
                    token_count=token_count,
                    reasoning_level=reasoning_level,
                    trace_id=trace_id,
                    principal=principal,
                )
            )
            row = (
                session.execute(select(turns).where(turns.c.id == turn_id))
                .mappings()
                .one()
            )
            return _to_turn(row)

    def list_turns(self, *, session_id: str) -> list[TurnRecord]:
        """List turns for one session ordered by ``created_at`` then ``id``."""
        session_id_bytes = ulid_str_to_bytes(session_id)
        with self._sessions.session() as session:
            rows = (
                session.execute(
                    select(turns)
                    .where(turns.c.session_id == session_id_bytes)
                    .order_by(turns.c.created_at.asc(), turns.c.id.asc())
                )
                .mappings()
                .all()
            )
            return [_to_turn(row) for row in rows]

    def get_latest_turn(self, *, session_id: str) -> TurnRecord | None:
        """Return latest turn for one session."""
        session_id_bytes = ulid_str_to_bytes(session_id)
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(turns)
                    .where(turns.c.session_id == session_id_bytes)
                    .order_by(desc(turns.c.created_at), desc(turns.c.id))
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else _to_turn(row)

    def list_turn_summaries(self, *, session_id: str) -> list[TurnSummaryRecord]:
        """List summary rows for one session ordered by create timestamp."""
        session_id_bytes = ulid_str_to_bytes(session_id)
        with self._sessions.session() as session:
            rows = (
                session.execute(
                    select(turn_summaries)
                    .where(turn_summaries.c.session_id == session_id_bytes)
                    .order_by(
                        turn_summaries.c.created_at.asc(),
                        turn_summaries.c.id.asc(),
                    )
                )
                .mappings()
                .all()
            )
            return [_to_turn_summary(row) for row in rows]

    def get_turn_summary_by_range(
        self,
        *,
        session_id: str,
        start_turn_id: str,
        end_turn_id: str,
    ) -> TurnSummaryRecord | None:
        """Read one summary row by exact range keys."""
        session_id_bytes = ulid_str_to_bytes(session_id)
        start_id_bytes = ulid_str_to_bytes(start_turn_id)
        end_id_bytes = ulid_str_to_bytes(end_turn_id)
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(turn_summaries).where(
                        turn_summaries.c.session_id == session_id_bytes,
                        turn_summaries.c.start_turn_id == start_id_bytes,
                        turn_summaries.c.end_turn_id == end_id_bytes,
                    )
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else _to_turn_summary(row)

    def create_turn_summary(
        self,
        *,
        session_id: str,
        start_turn_id: str,
        end_turn_id: str,
        content: str,
        token_count: int,
    ) -> TurnSummaryRecord:
        """Create one summary row idempotently by ``(session,start,end)``."""
        session_id_bytes = ulid_str_to_bytes(session_id)
        start_id_bytes = ulid_str_to_bytes(start_turn_id)
        end_id_bytes = ulid_str_to_bytes(end_turn_id)
        with self._sessions.session() as session:
            stmt = pg_insert(turn_summaries).values(
                id=generate_ulid_bytes(),
                session_id=session_id_bytes,
                start_turn_id=start_id_bytes,
                end_turn_id=end_id_bytes,
                content=content,
                token_count=token_count,
            )
            stmt = stmt.on_conflict_do_nothing(
                constraint="uq_turn_summary_session_range"
            )
            session.execute(stmt)

            row = (
                session.execute(
                    select(turn_summaries).where(
                        turn_summaries.c.session_id == session_id_bytes,
                        turn_summaries.c.start_turn_id == start_id_bytes,
                        turn_summaries.c.end_turn_id == end_id_bytes,
                    )
                )
                .mappings()
                .one()
            )
            return _to_turn_summary(row)


def _to_session(row: Mapping[str, object]) -> SessionRecord:
    """Map SQL row to ``SessionRecord``."""
    pointer = row.get("dialogue_start_turn_id")
    return SessionRecord(
        id=ulid_bytes_to_str(_row_bytes(row, "id")),
        focus=(None if row.get("focus") is None else str(row["focus"])),
        focus_token_count=(
            None
            if row.get("focus_token_count") is None
            else int(row["focus_token_count"])
        ),
        dialogue_start_turn_id=(
            None
            if pointer is None
            else ulid_bytes_to_str(_row_bytes(row, "dialogue_start_turn_id"))
        ),
        created_at=_row_dt(row, "created_at"),
        updated_at=_row_dt(row, "updated_at"),
    )


def _to_turn(row: Mapping[str, object]) -> TurnRecord:
    """Map SQL row to ``TurnRecord``."""
    return TurnRecord(
        id=ulid_bytes_to_str(_row_bytes(row, "id")),
        session_id=ulid_bytes_to_str(_row_bytes(row, "session_id")),
        direction=TurnDirection(str(row["direction"])),
        content=str(row["content"]),
        role=str(row["role"]),
        model=(None if row.get("model") is None else str(row["model"])),
        provider=(None if row.get("provider") is None else str(row["provider"])),
        token_count=None if row.get("token_count") is None else int(row["token_count"]),
        reasoning_level=(
            None if row.get("reasoning_level") is None else str(row["reasoning_level"])
        ),
        trace_id=str(row["trace_id"]),
        principal=str(row["principal"]),
        created_at=_row_dt(row, "created_at"),
    )


def _to_turn_summary(row: Mapping[str, object]) -> TurnSummaryRecord:
    """Map SQL row to ``TurnSummaryRecord``."""
    return TurnSummaryRecord(
        id=ulid_bytes_to_str(_row_bytes(row, "id")),
        session_id=ulid_bytes_to_str(_row_bytes(row, "session_id")),
        start_turn_id=ulid_bytes_to_str(_row_bytes(row, "start_turn_id")),
        end_turn_id=ulid_bytes_to_str(_row_bytes(row, "end_turn_id")),
        content=str(row["content"]),
        token_count=int(row["token_count"]),
        created_at=_row_dt(row, "created_at"),
    )


def _row_dt(row: Mapping[str, object], key: str) -> datetime:
    """Read one UTC-normalized datetime value from row mapping."""
    value = row.get(key)
    if not isinstance(value, datetime):
        raise ValueError(f"expected datetime column for {key}")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _row_bytes(row: Mapping[str, object], key: str) -> bytes:
    """Read one bytes value from row mapping."""
    value = row.get(key)
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    raise ValueError(f"expected bytes column for {key}")
