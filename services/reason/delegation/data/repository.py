"""Authoritative Postgres repository for Delegation Service state."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, insert, select, update

from lib.shared.ids import (
    generate_ulid_bytes,
    ulid_bytes_to_str,
    ulid_str_to_bytes,
)
from resources.substrates.postgres.schema_session import ServiceSchemaSessionProvider
from services.reason.delegation.domain import (
    CancelReason,
    ClaimedInvocation,
    InvocationRequest,
    InvocationResult,
    InvocationStatus,
    InvocationStatusView,
)

from .schema import invocations


class DelegationRepository:
    """SQL repository over Delegation-owned schema tables."""

    def __init__(self, sessions_provider: ServiceSchemaSessionProvider) -> None:
        self._sessions = sessions_provider

    # ------------------------------------------------------------------
    # Insertion
    # ------------------------------------------------------------------

    def insert_invocation(
        self,
        *,
        request: InvocationRequest,
        principal: str,
        channel: str,
        depth: int,
    ) -> str:
        """Persist one queued invocation and return its ULID string id."""
        invocation_id = generate_ulid_bytes()
        now = datetime.now(UTC)
        with self._sessions.session() as session:
            session.execute(
                insert(invocations).values(
                    id=invocation_id,
                    parent_invocation_id=(
                        ulid_str_to_bytes(request.parent_invocation_id)
                        if request.parent_invocation_id
                        else None
                    ),
                    depth=depth,
                    status=InvocationStatus.queued.value,
                    cancel_reason=None,
                    principal=principal,
                    channel=channel,
                    personality_id=request.personality_id,
                    prompt=request.prompt,
                    context_text=request.context_text,
                    context_object_refs=list(request.context_object_refs),
                    tool_allowlist=(
                        None
                        if request.tool_allowlist is None
                        else list(request.tool_allowlist)
                    ),
                    max_turns=request.max_turns,
                    budget_tokens=request.budget_tokens,
                    max_wallclock_seconds=request.max_wallclock_seconds,
                    created_at=now,
                    updated_at=now,
                )
            )
        return ulid_bytes_to_str(invocation_id)

    def read_depth(self, *, invocation_id: str) -> int | None:
        """Return the recorded depth for one invocation, or None if missing."""
        invocation_bytes = ulid_str_to_bytes(invocation_id)
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(invocations.c.depth).where(
                        invocations.c.id == invocation_bytes
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            return int(row["depth"])

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def read_status(self, *, invocation_id: str) -> InvocationStatusView | None:
        """Return the current status projection for one invocation row."""
        invocation_bytes = ulid_str_to_bytes(invocation_id)
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(invocations).where(invocations.c.id == invocation_bytes)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            return _to_status_view(row)

    def read_result(self, *, invocation_id: str) -> InvocationResult | None:
        """Return the terminal-or-current result projection for one invocation row."""
        invocation_bytes = ulid_str_to_bytes(invocation_id)
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(invocations).where(invocations.c.id == invocation_bytes)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            return _to_result(row)

    def read_ceilings(self, *, invocation_id: str) -> tuple[int, int | None] | None:
        """Return ``(max_turns, budget_tokens)`` ceilings for one invocation."""
        invocation_bytes = ulid_str_to_bytes(invocation_id)
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(invocations.c.max_turns, invocations.c.budget_tokens).where(
                        invocations.c.id == invocation_bytes
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            return int(row["max_turns"]), row["budget_tokens"]

    def list_children(self, *, parent_invocation_id: str) -> list[str]:
        """Return all invocation ids whose ``parent_invocation_id`` matches."""
        parent_bytes = ulid_str_to_bytes(parent_invocation_id)
        with self._sessions.session() as session:
            rows = (
                session.execute(
                    select(invocations.c.id).where(
                        invocations.c.parent_invocation_id == parent_bytes
                    )
                )
                .mappings()
                .all()
            )
            return [ulid_bytes_to_str(row["id"]) for row in rows]

    # ------------------------------------------------------------------
    # Claim / lifecycle transitions
    # ------------------------------------------------------------------

    def claim_next_queued(
        self, *, now: datetime, claimed_by: str
    ) -> ClaimedInvocation | None:
        """Atomically claim the oldest queued invocation, transitioning to running.

        Uses ``SELECT ... FOR UPDATE SKIP LOCKED`` so concurrent Subagent
        Actor callers do not double-claim the same row. Returns ``None`` when
        nothing is queued.
        """
        with self._sessions.session() as session:
            stmt = (
                select(invocations)
                .where(invocations.c.status == InvocationStatus.queued.value)
                .order_by(invocations.c.created_at, invocations.c.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            row = session.execute(stmt).mappings().one_or_none()
            if row is None:
                return None
            invocation_id = row["id"]
            session.execute(
                update(invocations)
                .where(invocations.c.id == invocation_id)
                .values(
                    status=InvocationStatus.running.value,
                    claimed_by=claimed_by,
                    claimed_at=now,
                    started_at=now,
                    updated_at=now,
                )
            )
            updated = (
                session.execute(
                    select(invocations).where(invocations.c.id == invocation_id)
                )
                .mappings()
                .one()
            )
            return _to_claimed(updated)

    def bump_turn_with_totals(
        self,
        *,
        invocation_id: str,
        tokens_in: int,
        tokens_out: int,
    ) -> InvocationStatusView | None:
        """Increment turn count and refresh authoritative token totals.

        Token columns are SET to the supplied totals (sourced from the
        Language audit aggregation), not incremented; this avoids drift
        when the loop replays or the actor is restarted mid-invocation.
        """
        invocation_bytes = ulid_str_to_bytes(invocation_id)
        now = datetime.now(UTC)
        with self._sessions.session() as session:
            session.execute(
                update(invocations)
                .where(invocations.c.id == invocation_bytes)
                .values(
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    turn_count=invocations.c.turn_count + 1,
                    updated_at=now,
                )
            )
            row = (
                session.execute(
                    select(invocations).where(invocations.c.id == invocation_bytes)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            return _to_status_view(row)

    def mark_canceling(
        self,
        *,
        invocation_id: str,
        reason: CancelReason,
    ) -> bool:
        """Flip a queued/running invocation to ``canceling``. Returns True if changed."""
        invocation_bytes = ulid_str_to_bytes(invocation_id)
        now = datetime.now(UTC)
        with self._sessions.session() as session:
            stmt = (
                update(invocations)
                .where(
                    and_(
                        invocations.c.id == invocation_bytes,
                        invocations.c.status.in_(
                            [
                                InvocationStatus.queued.value,
                                InvocationStatus.running.value,
                            ]
                        ),
                    )
                )
                .values(
                    status=InvocationStatus.canceling.value,
                    cancel_reason=reason.value,
                    updated_at=now,
                )
            )
            result = session.execute(stmt)
            return (result.rowcount or 0) > 0

    def finalize(
        self,
        *,
        invocation_id: str,
        status: InvocationStatus,
        final_response: str | None,
        transcript_ref: str | None = None,
        cancel_reason: CancelReason | None = None,
    ) -> InvocationResult | None:
        """Apply terminal state transition for one invocation row."""
        if status not in {
            InvocationStatus.succeeded,
            InvocationStatus.failed,
            InvocationStatus.canceled,
        }:
            raise ValueError(f"finalize called with non-terminal status {status}")
        invocation_bytes = ulid_str_to_bytes(invocation_id)
        now = datetime.now(UTC)
        with self._sessions.session() as session:
            session.execute(
                update(invocations)
                .where(invocations.c.id == invocation_bytes)
                .values(
                    status=status.value,
                    final_response=final_response,
                    transcript_ref=transcript_ref,
                    cancel_reason=(
                        None if cancel_reason is None else cancel_reason.value
                    ),
                    completed_at=now,
                    updated_at=now,
                )
            )
            row = (
                session.execute(
                    select(invocations).where(invocations.c.id == invocation_bytes)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            return _to_result(row)

    # ------------------------------------------------------------------
    # Sweepers
    # ------------------------------------------------------------------

    def sweep_wallclock(self, *, now: datetime) -> list[str]:
        """Mark running invocations past ``max_wallclock_seconds`` as canceling."""
        with self._sessions.session() as session:
            rows = (
                session.execute(
                    select(
                        invocations.c.id,
                        invocations.c.started_at,
                        invocations.c.max_wallclock_seconds,
                    ).where(
                        and_(
                            invocations.c.status == InvocationStatus.running.value,
                            invocations.c.max_wallclock_seconds.isnot(None),
                            invocations.c.started_at.isnot(None),
                        )
                    )
                )
                .mappings()
                .all()
            )
            stale: list[bytes] = []
            for row in rows:
                started_at = row["started_at"]
                max_seconds = row["max_wallclock_seconds"]
                if started_at is None or max_seconds is None:
                    continue
                if (now - started_at).total_seconds() >= max_seconds:
                    stale.append(row["id"])
            if len(stale) == 0:
                return []
            session.execute(
                update(invocations)
                .where(invocations.c.id.in_(stale))
                .values(
                    status=InvocationStatus.canceling.value,
                    cancel_reason=CancelReason.budget_wallclock.value,
                    updated_at=now,
                )
            )
            return [ulid_bytes_to_str(item) for item in stale]


# ----------------------------------------------------------------------
# Row mappers
# ----------------------------------------------------------------------


def _to_status_view(row: Any) -> InvocationStatusView:
    """Project one row mapping into the status read model."""
    return InvocationStatusView(
        invocation_id=ulid_bytes_to_str(row["id"]),
        status=InvocationStatus(row["status"]),
        cancel_reason=(
            None if row["cancel_reason"] is None else CancelReason(row["cancel_reason"])
        ),
        tokens_in=int(row["tokens_in"]),
        tokens_out=int(row["tokens_out"]),
        turn_count=int(row["turn_count"]),
        started_at=row["started_at"],
        completed_at=row["completed_at"],
    )


def _to_result(row: Any) -> InvocationResult:
    """Project one row mapping into the terminal/current result model."""
    return InvocationResult(
        invocation_id=ulid_bytes_to_str(row["id"]),
        status=InvocationStatus(row["status"]),
        final_response=row["final_response"],
        cancel_reason=(
            None if row["cancel_reason"] is None else CancelReason(row["cancel_reason"])
        ),
        tokens_in=int(row["tokens_in"]),
        tokens_out=int(row["tokens_out"]),
        turn_count=int(row["turn_count"]),
    )


def _to_claimed(row: Any) -> ClaimedInvocation:
    """Project one claimed-row mapping into a claim payload for actors."""
    parent_bytes = row["parent_invocation_id"]
    parent = None if parent_bytes is None else ulid_bytes_to_str(parent_bytes)
    refs = row["context_object_refs"]
    if not isinstance(refs, list):
        refs = []
    allowlist = row["tool_allowlist"]
    if allowlist is not None and not isinstance(allowlist, list):
        allowlist = list(allowlist)
    return ClaimedInvocation(
        invocation_id=ulid_bytes_to_str(row["id"]),
        parent_invocation_id=parent,
        principal=str(row["principal"]),
        channel=str(row["channel"]),
        personality_id=str(row["personality_id"]),
        prompt=str(row["prompt"]),
        context_text=row["context_text"],
        context_object_refs=tuple(str(item) for item in refs),
        tool_allowlist=(
            None if allowlist is None else tuple(str(item) for item in allowlist)
        ),
        max_turns=int(row["max_turns"]),
        budget_tokens=row["budget_tokens"],
        max_wallclock_seconds=row["max_wallclock_seconds"],
    )
