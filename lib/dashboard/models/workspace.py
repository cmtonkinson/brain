"""Workspace state models for the dashboard."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LayoutNode(BaseModel):
    """A node in the workspace layout tree.

    Either a split node (with children) or a leaf node (with pane_id).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    split: Literal["horizontal", "vertical"] | None = None
    children: "tuple[LayoutNode, LayoutNode] | None" = None
    pane_id: str | None = None
    view_id: str | None = None

    @model_validator(mode="after")
    def validate_node_type(self) -> "LayoutNode":
        is_split = self.split is not None
        has_children = self.children is not None
        has_pane = self.pane_id is not None

        if is_split:
            if not has_children:
                raise ValueError("Split nodes must have exactly two children")
            if has_pane:
                raise ValueError("Split nodes must not have a pane_id")
        else:
            if has_children:
                raise ValueError("Leaf nodes must not have children")
            if not has_pane:
                raise ValueError("Leaf nodes must have a pane_id")

        return self


LayoutNode.model_rebuild()


class InspectionContext(BaseModel):
    """Shared workspace-level inspection context for cross-view correlation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    turn_id: str | None = None
    trace_id: str | None = None
    envelope_id: str | None = None
    component: str | None = None
    provider: str | None = None
    model: str | None = None
    op_ref: str | None = None
    focal_timestamp: datetime | None = None
    time_range_start: datetime | None = None
    time_range_end: datetime | None = None
    source_pane_id: str | None = None
    published_at: datetime | None = None


class WorkspaceState(BaseModel):
    """Top-level workspace state for the dashboard."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    focused_pane_id: str | None = None
    maximized_pane_id: str | None = None
    root: LayoutNode | None = None
    inspection_context: InspectionContext = Field(default_factory=InspectionContext)
    pane_context_follow: dict[str, bool] = Field(default_factory=dict)
    pane_temporal_mode: dict[str, Literal["follow", "frozen"]] = Field(
        default_factory=dict
    )
