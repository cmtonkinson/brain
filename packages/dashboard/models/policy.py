"""Policy view models rendered by the Policy pane."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CurrentApprovalView(BaseModel):
    """Newest currently pending approval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: str = "pending"
    capability_id: str
    actor: str
    channel: str
    summary: str
    requested_at: datetime
    expires_at: datetime


class CurrentDecisionView(BaseModel):
    """Most recent policy decision (shown when no approval is pending)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_id: str
    actor: str
    channel: str
    state: str  # allowed | denied
    decided_at: datetime


class RecentPolicyItemView(BaseModel):
    """One row in the compact recent list (approval or decision)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp: datetime
    state: str  # allowed | denied | pending | approved | rejected | expired
    capability_id: str
