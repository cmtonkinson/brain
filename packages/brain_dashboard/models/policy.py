"""Policy view models rendered by the Policy pane."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PolicyDecisionView(BaseModel):
    """Summary of the current or selected policy decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_id: str = Field(min_length=1)
    autonomy_level: str = Field(min_length=1)
    decision: str = Field(min_length=1)
    reason_codes: tuple[str, ...] = ()
    approval_required: bool = Field(default=False)
