"""Domain models for the Embedding Authority Service (EAS).

These are transport-agnostic types used by east-west in-process callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Mapping


class EmbeddingStatus(StrEnum):
    """Lifecycle status for one chunk/spec embedding materialization."""

    PENDING = "pending"
    INDEXED = "indexed"
    FAILED = "failed"


@dataclass(frozen=True)
class EmbeddingSpec:
    """Authoritative embedding specification row."""

    id: str
    provider: str
    name: str
    version: str
    dimensions: int
    hash: bytes
    canonical_string: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class SourceRecord:
    """Authoritative source row owned by EAS."""

    id: str
    source_type: str
    canonical_reference: str
    service: str
    principal: str
    metadata: Mapping[str, str]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ChunkRecord:
    """Authoritative logical chunk row owned by EAS."""

    id: str
    source_id: str
    chunk_ordinal: int
    reference_range: str
    content_hash: str
    text: str
    metadata: Mapping[str, str]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class EmbeddingRecord:
    """Authoritative embedding materialization state for (chunk_id, spec_id)."""

    chunk_id: str
    spec_id: str
    content_hash: str
    status: EmbeddingStatus
    error_detail: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class UpsertChunkInput:
    """Input payload for one chunk upsert request."""

    source_id: str
    chunk_ordinal: int
    reference_range: str
    content_hash: str
    text: str
    metadata: Mapping[str, str]


@dataclass(frozen=True)
class UpsertChunkResult:
    """Result payload for one chunk upsert operation."""

    chunk: ChunkRecord
    embedding: EmbeddingRecord


@dataclass(frozen=True)
class RepairSpecResult:
    """Summary of one repair run for one embedding spec."""

    spec_id: str
    scanned: int
    repaired: int
    reembedded: int
