"""Trace view models rendered by the Trace pane."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TraceTreeNode(BaseModel):
    """One node in the trace tree, representing a single envelope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    envelope_id: str
    kind: str
    source: str
    timestamp: datetime
    parent_id: str | None = None
    children: tuple[TraceTreeNode, ...] = ()
    depth: int = 0


TraceTreeNode.model_rebuild()


class TraceTreeView(BaseModel):
    """Tree of trace nodes for the selected trace."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trace_id: str
    root_nodes: tuple[TraceTreeNode, ...] = ()


class TraceDetailView(BaseModel):
    """Full detail for a single selected envelope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    envelope_id: str
    kind: str
    source: str
    component: str | None = None
    timestamp: datetime
    payload_summary: str | None = None
    error: str | None = None
