"""Native domain types for Embedding Authority Service APIs.

These units define the authoritative, in-process data contract used by L1
services for east-west calls. gRPC/protobuf transport types are mapped to/from
these units at the adapter boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping


@dataclass(frozen=True)
class EmbeddingRef:
    """Canonical embedding key scoped by namespace."""

    namespace: str
    key: str


@dataclass(frozen=True)
class EmbeddingRecord:
    """Materialized embedding payload and metadata."""

    ref: EmbeddingRef
    vector: tuple[float, ...]
    model: str
    dimensions: int
    metadata: Mapping[str, str]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class EmbeddingMatch:
    """Similarity-search match with scored result."""

    ref: EmbeddingRef
    score: float
    metadata: Mapping[str, str]
