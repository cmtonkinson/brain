"""Turn data source: polls service_memory_authority.turn for current session."""

from __future__ import annotations

from packages.dashboard.data_sources.postgres import (
    BasePostgresDataSource,
    PostgresConnectionConfig,
)
from packages.dashboard.models.data_source import RetentionPolicy
from packages.dashboard.models.turn import CurrentTurnView, RecentTurnItemView


_RECENT_LIMIT = 20


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
            # Most recent N turns across all sessions (live dashboard shows latest session)
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

        # Determine active session from the most recent row
        latest = rows[0]
        active_session = latest[1]

        # Current = most recent inbound turn in the active session
        current: CurrentTurnView | None = None
        session_turns = [r for r in rows if r[1] == active_session]
        inbound_turns = [r for r in session_turns if r[2] == "inbound"]

        if inbound_turns:
            r = inbound_turns[0]
            # Count turns in session
            turn_count = len(session_turns)
            # Phase: if the most recent turn in session is outbound, it's complete; else active
            phase = "complete" if rows[0][2] == "outbound" else "active"
            # Model/provider from last outbound turn
            outbound = [r2 for r2 in session_turns if r2[2] == "outbound"]
            model_name = outbound[0][4] if outbound else ""
            provider = outbound[0][5] if outbound else ""
            token_count = outbound[0][6] if outbound else None
            current = CurrentTurnView(
                session_id=active_session,
                inbound_text=r[3],
                phase=phase,
                model_name=model_name,
                provider=provider,
                context_turn_count=turn_count,
                summary_count=0,
                token_count=token_count,
            )

        # Recent = all fetched rows as summary items
        recent: list[RecentTurnItemView] = []
        for r in rows:
            recent.append(
                RecentTurnItemView(
                    turn_id=r[0],
                    session_id=r[1],
                    inbound_preview=r[3][:80] if r[3] else "",
                    phase=r[2],
                    model_name=r[4],
                    recorded_at=r[7],
                )
            )

        return TurnSnapshot(current=current, recent=recent)
