"""Pydantic settings for the Embedding Service component."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class EmbeddingServiceSettings(BaseModel):
    """Embedding Service runtime configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_list_limit: int = Field(default=500, gt=0)
    default_list_limit: int = Field(default=100, gt=0)
