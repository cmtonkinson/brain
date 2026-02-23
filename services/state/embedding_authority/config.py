"""Pydantic settings for the Embedding Authority Service component."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EmbeddingServiceSettings(BaseModel):
    """Embedding Authority Service runtime configuration."""

    max_list_limit: int = Field(default=500, gt=0)
