"""Trace data source: polls call_audits and invocation_audits for recent traces."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from lib.dashboard.data_sources.postgres import (
    BasePostgresDataSource,
    PostgresConnectionConfig,
)
from lib.dashboard.models.data_source import RetentionPolicy
from lib.dashboard.models.trace import TraceTreeNode, TraceTreeView

_TRACE_LIMIT = 20

type TraceEnvelope = dict[str, Any]


def _normalize_parent_id(value: str | None) -> str | None:
    """Treat blank parent identifiers as no parent linkage."""
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _build_trace_tree(envelopes: list[TraceEnvelope]) -> tuple[TraceTreeNode, ...]:
    """Rebuild one trace DAG from envelope parent_id linkage."""
    child_ids_by_parent: dict[str, list[str]] = {}
    envelope_by_id = {str(item["envelope_id"]): item for item in envelopes}

    for item in envelopes:
        parent_id = _normalize_parent_id(item.get("parent_id"))
        if parent_id is None:
            continue
        child_ids_by_parent.setdefault(parent_id, []).append(str(item["envelope_id"]))

    def build_node(envelope_id: str, depth: int) -> TraceTreeNode:
        item = envelope_by_id[envelope_id]
        child_ids = sorted(
            child_ids_by_parent.get(envelope_id, []),
            key=lambda child_id: envelope_by_id[child_id]["timestamp"],
        )
        children = tuple(build_node(child_id, depth + 1) for child_id in child_ids)
        return TraceTreeNode(
            envelope_id=envelope_id,
            component=str(item["component"]),
            operation=str(item["operation"]),
            status=str(item["status"]),
            source=str(item["source"]),
            principal=(
                None if item.get("principal") in (None, "") else str(item["principal"])
            ),
            timestamp=item["timestamp"],
            parent_id=_normalize_parent_id(item.get("parent_id")),
            elapsed_ms=item.get("elapsed_ms"),
            children=children,
            depth=depth,
        )

    root_ids = [
        envelope_id
        for envelope_id, item in envelope_by_id.items()
        if _normalize_parent_id(item.get("parent_id")) not in envelope_by_id
    ]
    root_ids.sort(key=lambda envelope_id: envelope_by_id[envelope_id]["timestamp"])
    return tuple(build_node(root_id, depth=0) for root_id in root_ids)


class TraceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    traces: tuple[TraceTreeView, ...] = ()


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
            cur.execute(
                """
                SELECT trace_id, envelope_id, parent_id, source, principal, operation, outcome_kind, duration_ms, created_at
                FROM service_language.call_audits
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (_TRACE_LIMIT * 4,),
            )
            call_rows = cur.fetchall()

            cur.execute(
                """
                SELECT trace_id, envelope_id, parent_id, source, actor, op_id, allowed, created_at
                FROM service_execution.invocation_audits
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (_TRACE_LIMIT * 4,),
            )
            inv_rows = cur.fetchall()

        envelopes: dict[str, list[TraceEnvelope]] = {}

        for row in call_rows:
            (
                trace_id,
                envelope_id,
                parent_id,
                source,
                principal,
                operation,
                outcome_kind,
                duration_ms,
                created_at,
            ) = row
            envelopes.setdefault(trace_id, []).append(
                {
                    "envelope_id": envelope_id,
                    "parent_id": parent_id,
                    "component": source,
                    "operation": operation,
                    "status": outcome_kind.upper(),
                    "source": source,
                    "principal": principal,
                    "elapsed_ms": (
                        None if duration_ms is None else int(round(float(duration_ms)))
                    ),
                    "timestamp": created_at,
                }
            )

        for row in inv_rows:
            (
                trace_id,
                envelope_id,
                parent_id,
                source,
                actor,
                op_id,
                allowed,
                created_at,
            ) = row
            envelopes.setdefault(trace_id, []).append(
                {
                    "envelope_id": envelope_id,
                    "parent_id": parent_id,
                    "component": source,
                    "operation": op_id,
                    "status": "OK" if allowed else "DENIED",
                    "source": source,
                    "principal": actor,
                    "elapsed_ms": None,
                    "timestamp": created_at,
                }
            )

        trace_latest: dict[str, datetime] = {}
        for trace_id, items in envelopes.items():
            trace_latest[trace_id] = max(item["timestamp"] for item in items)

        recent_traces = sorted(
            trace_latest, key=lambda trace_id: trace_latest[trace_id], reverse=True
        )[:_TRACE_LIMIT]

        trees = []
        for trace_id in recent_traces:
            roots = _build_trace_tree(envelopes[trace_id])
            selected_node_id = None
            if roots:
                flattened = sorted(
                    envelopes[trace_id],
                    key=lambda item: item["timestamp"],
                    reverse=True,
                )
                selected_node_id = str(flattened[0]["envelope_id"])
            trees.append(
                TraceTreeView(
                    trace_id=trace_id,
                    root_nodes=roots,
                    selected_node_id=selected_node_id,
                )
            )

        return TraceSnapshot(traces=tuple(trees))
