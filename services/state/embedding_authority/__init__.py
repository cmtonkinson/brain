"""Embedding Authority Service native package exports."""

from packages.brain_shared.config import EmbeddingServiceSettings
from packages.brain_shared.envelope import EnvelopeKind, EnvelopeMeta, Envelope
from packages.brain_shared.errors import ErrorCategory, ErrorDetail
from services.state.embedding_authority.component import MANIFEST
from services.state.embedding_authority.domain import (
    ChunkRecord,
    EmbeddingRecord,
    EmbeddingSpec,
    EmbeddingStatus,
    SearchEmbeddingMatch,
    SourceRecord,
    UpsertChunkInput,
    UpsertEmbeddingVectorInput,
)
from services.state.embedding_authority.implementation import (
    DefaultEmbeddingAuthorityService,
)
from services.state.embedding_authority.service import EmbeddingAuthorityService

__all__ = [
    "EmbeddingAuthorityService",
    "EmbeddingServiceSettings",
    "DefaultEmbeddingAuthorityService",
    "EmbeddingSpec",
    "SourceRecord",
    "ChunkRecord",
    "EmbeddingRecord",
    "EmbeddingStatus",
    "SearchEmbeddingMatch",
    "UpsertChunkInput",
    "UpsertEmbeddingVectorInput",
    "EnvelopeKind",
    "EnvelopeMeta",
    "ErrorCategory",
    "ErrorDetail",
    "Envelope",
    "MANIFEST",
]
