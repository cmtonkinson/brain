"""Embedding Authority Service native package exports."""

from packages.brain_shared.envelope import EnvelopeKind, EnvelopeMeta, Result
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
from services.state.embedding_authority.settings import EmbeddingSettings

__all__ = [
    "EmbeddingAuthorityService",
    "EmbeddingSettings",
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
    "Result",
    "MANIFEST",
]
