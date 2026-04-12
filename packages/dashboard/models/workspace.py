"""Workspace state models for the dashboard."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


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


class WorkspaceState(BaseModel):
    """Top-level workspace state for the dashboard."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    focused_pane_id: str | None = None
    maximized_pane_id: str | None = None
    root: LayoutNode | None = None
