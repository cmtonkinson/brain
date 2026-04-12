"""Trace data source: polls call_audits and invocation_audits for recent traces."""

from __future__ import annotations

from datetime import datetime, timezone

from packages.dashboard.data_sources.postgres import (
    BasePostgresDataSource,
    PostgresConnectionConfig,
)
from packages.dashboard.models.data_source import RetentionPolicy
from packages.dashboard.models.trace import TraceDetailView, TraceTreeNode, TraceTreeView


_TRACE_LIMIT = 20  # most recent distinct traces to show


class TraceSnapshot:
    __slots__ = ("traces",)

    def __init__(self, traces: list[TraceTreeView]) -> None:
        self.traces = traces


class TraceDataSource(BasePostgresDataSource[TraceSnapshot]):
    def __init__(self, config: PostgresConnectionConfig, poll_interval: float) -> None:
        super().__init__(
            config=config,
            poll_interval=poll_interval,
            retention=RetentionPolicy(family="snapshot", max_items=50),
        )

    def _fetch(self) -> TraceSnapshot | None:  # type: ignore[override]
        conn = self._get_connection()
        with conn.cursor() as cur:
            # Fetch recent call audit rows
            cur.execute(
                """
                SELECT trace_id, envelope_id, parent_id, source, operation, outcome_kind, created_at
                FROM service_language_model.call_audits
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (_TRACE_LIMIT * 4,),
            )
            call_rows = cur.fetchall()

            # Fetch recent invocation audit rows for the same traces
            cur.execute(
                """
                SELECT trace_id, envelope_id, parent_id, source, capability_id, allowed, created_at
                FROM service_capability_engine.invocation_audits
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (_TRACE_LIMIT * 4,),
            )
            inv_rows = cur.fetchall()

        # Build per-trace envelope lists
        # Each entry: (trace_id, envelope_id, parent_id, source, kind, created_at)
        envelopes: dict[str, list[tuple]] = {}

        for r in call_rows:
            trace_id, envelope_id, parent_id, source, operation, outcome_kind, created_at = r
            kind = f"{operation}/{outcome_kind}"
            envelopes.setdefault(trace_id, []).append(
                (trace_id, envelope_id, parent_id or None, source, kind, created_at)
            )

        for r in inv_rows:
            trace_id, envelope_id, parent_id, source, capability_id, allowed, created_at = r
            kind = f"cap:{capability_id}" + ("" if allowed else " [denied]")
            envelopes.setdefault(trace_id, []).append(
                (trace_id, envelope_id, parent_id or None, source, kind, created_at)
            )

        # Sort traces by most recent activity, take top N
        trace_latest: dict[str, datetime] = {}
        for trace_id, evs in envelopes.items():
            trace_latest[trace_id] = max(e[5] for e in evs)

        recent_traces = sorted(trace_latest, key=lambda t: trace_latest[t], reverse=True)[
            :_TRACE_LIMIT
        ]

        trees: list[TraceTreeView] = []
        for trace_id in recent_traces:
            evs = sorted(envelopes[trace_id], key=lambda e: e[5])
            children = tuple(
                TraceTreeNode(
                    envelope_id=e[1],
                    kind=e[4],
                    source=e[3],
                    timestamp=e[5],
                    parent_id=e[2],
                    depth=1,
                )
                for e in evs
            )
            # Root node represents the trace itself
            root = TraceTreeNode(
                envelope_id=trace_id,
                kind="trace",
                source=evs[0][3] if evs else "?",
                timestamp=trace_latest[trace_id],
                parent_id=None,
                children=children,
                depth=0,
            )
            trees.append(TraceTreeView(trace_id=trace_id, root_nodes=(root,)))

        return TraceSnapshot(traces=trees)
