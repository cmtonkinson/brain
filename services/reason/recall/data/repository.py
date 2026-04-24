"""Authoritative Postgres repository for Recall Service state."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import desc, insert, select, update

from lib.shared.ids import (
    generate_ulid_str,
    generate_ulid_bytes,
    ulid_bytes_to_str,
    ulid_str_to_bytes,
)
from resources.substrates.postgres.schema_session import ServiceSchemaSessionProvider
from services.reason.recall.domain import (
    InboundInstructionRecord,
    SessionRecord,
    TurnDirection,
    OutboundDeliveryRecord,
    TurnRecord,
)

from .schema import sessions, turns


class MemoryRepository(Protocol):
    """Protocol for Recall authoritative persistence operations."""

    def create_session(self) -> SessionRecord:
        """Create and return one session row."""

    def get_latest_session(self) -> SessionRecord | None:
        """Read the most recently updated session row."""

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

    def update_dialogue_summary(
        self,
        *,
        session_id: str,
        dialogue_summary: str | None,
        dialogue_summary_token_count: int | None,
        dialogue_start_turn_id: str | None,
    ) -> SessionRecord | None:
        """Update rolling summary text and checkpoint for one session."""

    def resolve_conversation_episode(
        self,
        *,
        session_id: str,
        inbound_at: datetime,
        idle_seconds: int,
    ) -> str | None:
        """Return the current or newly rotated conversation episode id."""

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
        conversation_episode_id: str,
        principal: str,
        source: str | None = None,
        instruction: InboundInstructionRecord | None = None,
        delivery: OutboundDeliveryRecord | None = None,
    ) -> TurnRecord:
        """Insert one dialogue turn row and return it."""

    def list_turns(self, *, session_id: str) -> list[TurnRecord]:
        """List dialogue turns ordered by creation time."""

    def get_latest_turn(self, *, session_id: str) -> TurnRecord | None:
        """Read latest turn for one session."""

    def update_turn_delivery(
        self,
        *,
        turn_id: str,
        delivery: OutboundDeliveryRecord,
    ) -> TurnRecord | None:
        """Update one outbound turn with final delivery state."""


class PostgresMemoryRepository:
    """SQL repository over Recall-owned schema tables."""

    def __init__(self, sessions_provider: ServiceSchemaSessionProvider) -> None:
        self._sessions = sessions_provider

    def create_session(self) -> SessionRecord:
        """Create and return one new session row."""
        session_id = generate_ulid_bytes()
        episode_id = generate_ulid_str()
        with self._sessions.session() as session:
            session.execute(
                insert(sessions).values(
                    id=session_id,
                    focus=None,
                    focus_token_count=None,
                    dialogue_summary=None,
                    dialogue_summary_token_count=None,
                    dialogue_start_turn_id=None,
                    current_conversation_episode_id=episode_id,
                    last_episode_inbound_at=None,
                )
            )
            row = (
                session.execute(select(sessions).where(sessions.c.id == session_id))
                .mappings()
                .one()
            )
            return _to_session(row)

    def get_latest_session(self) -> SessionRecord | None:
        """Read the most recently updated session row."""
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(sessions)
                    .order_by(desc(sessions.c.updated_at), desc(sessions.c.id))
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else _to_session(row)

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
                    dialogue_summary=None,
                    dialogue_summary_token_count=None,
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

    def update_dialogue_summary(
        self,
        *,
        session_id: str,
        dialogue_summary: str | None,
        dialogue_summary_token_count: int | None,
        dialogue_start_turn_id: str | None,
    ) -> SessionRecord | None:
        """Update rolling summary text and checkpoint for one session."""
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
                    dialogue_summary=dialogue_summary,
                    dialogue_summary_token_count=dialogue_summary_token_count,
                    dialogue_start_turn_id=pointer,
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

    def resolve_conversation_episode(
        self,
        *,
        session_id: str,
        inbound_at: datetime,
        idle_seconds: int,
    ) -> str | None:
        """Return the current or newly rotated conversation episode id."""
        session_id_bytes = ulid_str_to_bytes(session_id)
        normalized_inbound_at = (
            inbound_at.replace(tzinfo=UTC)
            if inbound_at.tzinfo is None
            else inbound_at.astimezone(UTC)
        )
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(sessions).where(sessions.c.id == session_id_bytes)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None

            current_episode = row.get("current_conversation_episode_id")
            current_episode_id = (
                "" if current_episode is None else str(current_episode).strip()
            )
            last_inbound = row.get("last_episode_inbound_at")
            rotate = current_episode_id == ""
            if not rotate:
                if isinstance(last_inbound, datetime):
                    last_at = (
                        last_inbound.replace(tzinfo=UTC)
                        if last_inbound.tzinfo is None
                        else last_inbound.astimezone(UTC)
                    )
                    rotate = (
                        normalized_inbound_at - last_at
                    ).total_seconds() > idle_seconds

            episode_id = generate_ulid_str() if rotate else current_episode_id
            session.execute(
                update(sessions)
                .where(sessions.c.id == session_id_bytes)
                .values(
                    current_conversation_episode_id=episode_id,
                    last_episode_inbound_at=normalized_inbound_at,
                    updated_at=datetime.now(UTC),
                )
            )
            return episode_id

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
        conversation_episode_id: str,
        principal: str,
        source: str | None = None,
        instruction: InboundInstructionRecord | None = None,
        delivery: OutboundDeliveryRecord | None = None,
    ) -> TurnRecord:
        """Insert one turn row and return mapped domain record."""
        turn_id = generate_ulid_bytes()
        session_id_bytes = ulid_str_to_bytes(session_id)
        instruction_values = _instruction_row_values(instruction)
        delivery_values = _delivery_row_values(delivery)
        resolved_source = source
        if resolved_source is None and instruction is not None:
            resolved_source = instruction.source
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
                    conversation_episode_id=conversation_episode_id,
                    principal=principal,
                    source=resolved_source,
                    **instruction_values,
                    **delivery_values,
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

    def update_turn_delivery(
        self,
        *,
        turn_id: str,
        delivery: OutboundDeliveryRecord,
    ) -> TurnRecord | None:
        """Update one turn delivery fields and return latest row."""
        turn_id_bytes = ulid_str_to_bytes(turn_id)
        with self._sessions.session() as session:
            result = session.execute(
                update(turns)
                .where(turns.c.id == turn_id_bytes)
                .values(**_delivery_row_values(delivery))
            )
            if int(result.rowcount or 0) == 0:
                return None
            row = (
                session.execute(select(turns).where(turns.c.id == turn_id_bytes))
                .mappings()
                .one()
            )
            return _to_turn(row)


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
        dialogue_summary=(
            None
            if row.get("dialogue_summary") is None
            else str(row["dialogue_summary"])
        ),
        dialogue_summary_token_count=(
            None
            if row.get("dialogue_summary_token_count") is None
            else int(row["dialogue_summary_token_count"])
        ),
        dialogue_start_turn_id=(
            None
            if pointer is None
            else ulid_bytes_to_str(_row_bytes(row, "dialogue_start_turn_id"))
        ),
        current_conversation_episode_id=(
            None
            if row.get("current_conversation_episode_id") is None
            else str(row["current_conversation_episode_id"])
        ),
        last_episode_inbound_at=(
            None
            if row.get("last_episode_inbound_at") is None
            else _row_dt(row, "last_episode_inbound_at")
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
        conversation_episode_id=str(row["conversation_episode_id"]),
        principal=str(row["principal"]),
        source=(None if row.get("source") is None else str(row["source"])),
        sender_e164=(
            None if row.get("sender_e164") is None else str(row["sender_e164"])
        ),
        timestamp_ms=(
            None if row.get("timestamp_ms") is None else int(row["timestamp_ms"])
        ),
        source_device=(
            None if row.get("source_device") is None else str(row["source_device"])
        ),
        group_id=(None if row.get("group_id") is None else str(row["group_id"])),
        quote_target_timestamp_ms=(
            None
            if row.get("quote_target_timestamp_ms") is None
            else int(row["quote_target_timestamp_ms"])
        ),
        reaction_target_timestamp_ms=(
            None
            if row.get("reaction_target_timestamp_ms") is None
            else int(row["reaction_target_timestamp_ms"])
        ),
        reaction_emoji=(
            None if row.get("reaction_emoji") is None else str(row["reaction_emoji"])
        ),
        approval_intent=(
            None if row.get("approval_intent") is None else str(row["approval_intent"])
        ),
        reply_to_proposal_token=(
            None
            if row.get("reply_to_proposal_token") is None
            else str(row["reply_to_proposal_token"])
        ),
        reaction_to_proposal_token=(
            None
            if row.get("reaction_to_proposal_token") is None
            else str(row["reaction_to_proposal_token"])
        ),
        delivery_state=(
            None if row.get("delivery_state") is None else str(row["delivery_state"])
        ),
        delivery_timestamp_ms=(
            None
            if row.get("delivery_timestamp_ms") is None
            else int(row["delivery_timestamp_ms"])
        ),
        delivery_detail=(
            None if row.get("delivery_detail") is None else str(row["delivery_detail"])
        ),
        created_at=_row_dt(row, "created_at"),
    )


def _instruction_row_values(
    instruction: InboundInstructionRecord | None,
) -> dict[str, object]:
    """Return SQL row values for one inbound instruction metadata bundle."""
    if instruction is None:
        return {}
    return {
        "sender_e164": instruction.sender_e164,
        "timestamp_ms": instruction.timestamp_ms,
        "source_device": instruction.source_device,
        "group_id": instruction.group_id,
        "quote_target_timestamp_ms": instruction.quote_target_timestamp_ms,
        "reaction_target_timestamp_ms": instruction.reaction_target_timestamp_ms,
        "reaction_emoji": instruction.reaction_emoji,
        "approval_intent": instruction.approval_intent,
        "reply_to_proposal_token": instruction.reply_to_proposal_token,
        "reaction_to_proposal_token": instruction.reaction_to_proposal_token,
    }


def _delivery_row_values(delivery: OutboundDeliveryRecord | None) -> dict[str, object]:
    """Return SQL row values for one outbound delivery state bundle."""
    if delivery is None:
        return {}
    return {
        "delivery_state": delivery.state,
        "delivery_timestamp_ms": delivery.delivered_at_ms,
        "delivery_detail": delivery.detail,
    }


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
