"""Trace view models rendered by the Trace pane."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TraceTreeNode(BaseModel):
    """One node in the trace tree, representing a single envelope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    envelope_id: str
    component: str
    operation: str
    status: str
    source: str
    principal: str | None = None
    timestamp: datetime
    parent_id: str | None = None
    elapsed_ms: int | None = None
    children: tuple[TraceTreeNode, ...] = ()
    depth: int = 0


TraceTreeNode.model_rebuild()


class TraceTreeView(BaseModel):
    """Tree of trace nodes for the selected trace."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trace_id: str
    root_nodes: tuple[TraceTreeNode, ...] = ()
    selected_node_id: str | None = None


class TraceDetailView(BaseModel):
    """Full detail for a single selected envelope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    envelope_id: str
    component: str
    operation: str
    status: str
    source: str
    principal: str | None = None
    timestamp: datetime
    parent_id: str | None = None
    elapsed_ms: int | None = None
    payload_summary: str | None = None
    errors: tuple[str, ...] = ()
