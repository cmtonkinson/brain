"""Domain models for the Embedding Authority Service (EAS).

These are transport-agnostic types used by east-west in-process callers.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Mapping, Sequence

from pydantic import BaseModel, ConfigDict


class EmbeddingStatus(StrEnum):
    """Lifecycle status for one chunk/spec embedding materialization."""

    PENDING = "pending"
    INDEXED = "indexed"
    FAILED = "failed"


class EmbeddingSpec(BaseModel):
    """Authoritative embedding specification row."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    provider: str
    name: str
    version: str
    dimensions: int
    hash: bytes
    canonical_string: str
    created_at: datetime
    updated_at: datetime


class SourceRecord(BaseModel):
    """Authoritative source row owned by EAS."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    source_type: str
    canonical_reference: str
    service: str
    principal: str
    metadata: Mapping[str, str]
    created_at: datetime
    updated_at: datetime


class ChunkRecord(BaseModel):
    """Authoritative logical chunk row owned by EAS."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    source_id: str
    chunk_ordinal: int
    reference_range: str
    content_hash: str
    text: str
    metadata: Mapping[str, str]
    created_at: datetime
    updated_at: datetime


class EmbeddingRecord(BaseModel):
    """Authoritative embedding materialization state for (chunk_id, spec_id)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str
    spec_id: str
    content_hash: str
    status: EmbeddingStatus
    error_detail: str
    created_at: datetime
    updated_at: datetime


class SearchEmbeddingMatch(BaseModel):
    """Derived semantic-search match returned by EAS query operations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    score: float
    chunk_id: str
    source_id: str
    spec_id: str
    chunk_ordinal: int
    reference_range: str
    content_hash: str


class UpsertChunkInput(BaseModel):
    """Input payload for one chunk upsert request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str
    chunk_ordinal: int
    reference_range: str
    content_hash: str
    text: str
    metadata: Mapping[str, str]


class UpsertEmbeddingVectorInput(BaseModel):
    """Input payload for one vector upsert request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str
    spec_id: str
    vector: Sequence[float]


class HealthStatus(BaseModel):
    """EAS and owned dependency readiness status payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    service_ready: bool
    substrate_ready: bool
    detail: str
