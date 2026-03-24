"""Trace view models rendered by the Trace pane."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TraceEventView(BaseModel):
    """One concise event in the active trace timeline."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    name: str = Field(min_length=1)


class TraceView(BaseModel):
    """Compact representation of the currently selected trace."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trace_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    current_step: str = Field(min_length=1)
    events: tuple[TraceEventView, ...] = ()
