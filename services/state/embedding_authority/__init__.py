"""Embedding Authority Service package exports."""

from services.state.embedding_authority.api import (
    GrpcEmbeddingAuthorityService,
    register_embedding_authority_service,
)
from packages.brain_shared.envelope import EnvelopeKind, EnvelopeMeta, Result
from packages.brain_shared.errors import ErrorCategory, ErrorDetail
from services.state.embedding_authority.domain import EmbeddingMatch, EmbeddingRecord, EmbeddingRef
from services.state.embedding_authority.implementation import DefaultEmbeddingAuthorityService
from services.state.embedding_authority.service import EmbeddingAuthorityService
from services.state.embedding_authority.settings import EmbeddingSettings

__all__ = [
    "EmbeddingAuthorityService",
    "EmbeddingMatch",
    "EmbeddingRecord",
    "EmbeddingRef",
    "EmbeddingSettings",
    "DefaultEmbeddingAuthorityService",
    "EnvelopeKind",
    "EnvelopeMeta",
    "ErrorCategory",
    "ErrorDetail",
    "GrpcEmbeddingAuthorityService",
    "Result",
    "register_embedding_authority_service",
]
