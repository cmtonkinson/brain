"""Turn data source: polls service_memory_authority.turn for current session."""

from __future__ import annotations

from datetime import datetime, timezone

from lib.dashboard.data_sources.postgres import (
    BasePostgresDataSource,
    PostgresConnectionConfig,
)
from lib.dashboard.models.data_source import RetentionPolicy
from lib.dashboard.models.turn import CurrentTurnView, RecentTurnItemView

_RECENT_LIMIT = 20
_SUMMARY_LIMIT = 80

type TurnRow = tuple[
    str,
    str,
    str,
    str,
    str,
    str,
    int | None,
    str | None,
    str,
    str,
    datetime,
]


def _summarize_content(content: str, limit: int = _SUMMARY_LIMIT) -> str:
    """Return one compact dialogue preview line."""
    normalized = " ".join(content.split())
    return normalized if len(normalized) <= limit else normalized[:limit] + "..."


def _build_recent_turns(rows: list[TurnRow]) -> list[RecentTurnItemView]:
    """Normalize recent turn rows for the compact recent list."""
    return [
        RecentTurnItemView(
            timestamp=row[10],
            direction="in" if row[2] == "inbound" else "out",
            summary=_summarize_content(row[3]),
        )
        for row in rows
    ]


def _build_current_turn(session_turns: list[TurnRow]) -> CurrentTurnView | None:
    """Pair the newest inbound turn with the next outbound response when present."""
    if not session_turns:
        return None

    descending = sorted(session_turns, key=lambda row: row[10], reverse=True)
    inbound = next((row for row in descending if row[2] == "inbound"), None)
    if inbound is None:
        return None

    outbound = next(
        (row for row in descending if row[2] == "outbound" and row[10] > inbound[10]),
        None,
    )

    if outbound is None:
        elapsed_ms = max(
            0,
            int((datetime.now(timezone.utc) - inbound[10]).total_seconds() * 1000),
        )
        return CurrentTurnView(
            state="pending",
            inbound_content=inbound[3],
            inbound_time=inbound[10],
            inbound_principal=inbound[9],
            response_content=None,
            response_time=None,
            model=None,
            provider=None,
            reasoning_level=None,
            token_count=None,
            trace_id=inbound[8],
            elapsed_ms=elapsed_ms,
        )

    elapsed_ms = max(0, int((outbound[10] - inbound[10]).total_seconds() * 1000))
    return CurrentTurnView(
        state="complete",
        inbound_content=inbound[3],
        inbound_time=inbound[10],
        inbound_principal=inbound[9],
        response_content=outbound[3],
        response_time=outbound[10],
        model=outbound[4] or None,
        provider=outbound[5] or None,
        reasoning_level=outbound[7] or None,
        token_count=outbound[6],
        trace_id=outbound[8] or inbound[8],
        elapsed_ms=elapsed_ms,
    )


class TurnSnapshot:
    """Holds the latest turn state fetched from postgres."""

    __slots__ = ("current", "recent")

    def __init__(
        self,
        current: CurrentTurnView | None,
        recent: list[RecentTurnItemView],
    ) -> None:
        self.current = current
        self.recent = recent


class TurnDataSource(BasePostgresDataSource[TurnSnapshot]):
    """Polls the turn table and produces CurrentTurnView + recent history."""

    def __init__(self, config: PostgresConnectionConfig, poll_interval: float) -> None:
        super().__init__(
            config=config,
            poll_interval=poll_interval,
            retention=RetentionPolicy(family="snapshot", max_items=100),
        )

    def _fetch(self) -> TurnSnapshot | None:  # type: ignore[override]
        conn = self._get_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    encode(id, 'hex'),
                    encode(session_id, 'hex'),
                    direction,
                    content,
                    COALESCE(model, ''),
                    COALESCE(provider, ''),
                    token_count,
                    reasoning_level,
                    trace_id,
                    principal,
                    created_at
                FROM service_memory_authority.turn
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (_RECENT_LIMIT + 1,),
            )
            rows = cur.fetchall()

        if not rows:
            return TurnSnapshot(current=None, recent=[])

        active_session = rows[0][1]
        session_turns = [row for row in rows if row[1] == active_session]
        return TurnSnapshot(
            current=_build_current_turn(session_turns),
            recent=_build_recent_turns(rows),
        )
