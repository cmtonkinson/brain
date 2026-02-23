"""Pydantic request models for Embedding Authority Service validation."""

from __future__ import annotations

from typing import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

from packages.brain_shared.ids import ulid_str_to_bytes
from services.state.embedding_authority.domain import (
    UpsertChunkInput,
    UpsertEmbeddingVectorInput,
)


class _ValidationModel(BaseModel):
    """Base request model with strict shape semantics."""

    model_config = ConfigDict(frozen=True, extra="forbid")


def _require_text(value: str, *, field_name: str) -> str:
    """Require one non-empty text field with stable error message."""
    normalized = value.strip()
    if normalized == "":
        raise ValueError(f"{field_name} is required")
    return normalized


def _require_ulid(value: str, *, field_name: str) -> str:
    """Require one valid ULID string with stable error messages."""
    normalized = value.strip()
    if normalized == "":
        raise ValueError(f"{field_name} is required")
    try:
        ulid_str_to_bytes(normalized)
    except ValueError:
        raise ValueError(f"{field_name} must be a valid ULID string") from None
    return normalized


def _optional_ulid(value: str, *, field_name: str) -> str:
    """Allow empty string or one valid ULID string."""
    normalized = value.strip()
    if normalized == "":
        return ""
    try:
        ulid_str_to_bytes(normalized)
    except ValueError:
        raise ValueError(f"{field_name} must be a valid ULID string") from None
    return normalized


class SpecUpsertRequest(_ValidationModel):
    """Validated request shape for embedding spec upsert operations."""

    provider: str
    name: str
    version: str
    dimensions: int

    @field_validator("provider", "name", "version")
    @classmethod
    def _validate_text(cls, value: str, info: ValidationInfo) -> str:
        """Validate required textual fields."""
        return _require_text(value, field_name=info.field_name)

    @field_validator("dimensions")
    @classmethod
    def _validate_dimensions(cls, value: int) -> int:
        """Require positive dimensions."""
        if value <= 0:
            raise ValueError("dimensions must be > 0")
        return value


class SpecIdRequest(_ValidationModel):
    """Validated request shape requiring one spec ULID."""

    spec_id: str

    @field_validator("spec_id")
    @classmethod
    def _validate_spec_id(cls, value: str, info: ValidationInfo) -> str:
        """Validate one required ULID identifier."""
        return _require_ulid(value, field_name=info.field_name)


class SourceIdRequest(_ValidationModel):
    """Validated request shape requiring one source ULID."""

    source_id: str

    @field_validator("source_id")
    @classmethod
    def _validate_source_id(cls, value: str, info: ValidationInfo) -> str:
        """Validate one required ULID identifier."""
        return _require_ulid(value, field_name=info.field_name)


class ChunkIdRequest(_ValidationModel):
    """Validated request shape requiring one chunk ULID."""

    chunk_id: str

    @field_validator("chunk_id")
    @classmethod
    def _validate_chunk_id(cls, value: str, info: ValidationInfo) -> str:
        """Validate one required ULID identifier."""
        return _require_ulid(value, field_name=info.field_name)


class SourceUpsertRequest(_ValidationModel):
    """Validated request shape for source upsert operations."""

    canonical_reference: str
    source_type: str
    service: str
    principal: str
    metadata: Mapping[str, str]

    @field_validator("canonical_reference", "source_type", "service", "principal")
    @classmethod
    def _validate_text(cls, value: str, info: ValidationInfo) -> str:
        """Validate required textual fields."""
        return _require_text(value, field_name=info.field_name)


class ChunkUpsertRequest(_ValidationModel):
    """Validated request shape for chunk upsert operations."""

    source_id: str
    chunk_ordinal: int
    reference_range: str
    content_hash: str
    text: str
    metadata: Mapping[str, str]

    @field_validator("source_id")
    @classmethod
    def _validate_source_id(cls, value: str, info: ValidationInfo) -> str:
        """Validate required ULID fields."""
        return _require_ulid(value, field_name=info.field_name)

    @field_validator("content_hash", "text")
    @classmethod
    def _validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        """Validate required non-empty text fields."""
        return _require_text(value, field_name=info.field_name)

    @field_validator("chunk_ordinal")
    @classmethod
    def _validate_chunk_ordinal(cls, value: int) -> int:
        """Require non-negative chunk ordinals."""
        if value < 0:
            raise ValueError("chunk_ordinal must be >= 0")
        return value


class EmbeddingVectorUpsertRequest(_ValidationModel):
    """Validated request shape for vector upsert operations."""

    chunk_id: str
    spec_id: str
    vector: Sequence[float]

    @field_validator("chunk_id")
    @classmethod
    def _validate_chunk_id(cls, value: str, info: ValidationInfo) -> str:
        """Validate required ULID fields."""
        return _require_ulid(value, field_name=info.field_name)

    @field_validator("spec_id")
    @classmethod
    def _validate_spec_id(cls, value: str, info: ValidationInfo) -> str:
        """Validate optional ULID fields."""
        return _optional_ulid(value, field_name=info.field_name)

    @field_validator("vector")
    @classmethod
    def _validate_vector(cls, value: Sequence[float]) -> Sequence[float]:
        """Require non-empty vectors."""
        if len(value) == 0:
            raise ValueError("vector is required")
        return value


class GetEmbeddingRequest(_ValidationModel):
    """Validated request shape for one embedding lookup."""

    chunk_id: str
    spec_id: str

    @field_validator("chunk_id")
    @classmethod
    def _validate_chunk_id(cls, value: str, info: ValidationInfo) -> str:
        """Validate required ULID fields."""
        return _require_ulid(value, field_name=info.field_name)

    @field_validator("spec_id")
    @classmethod
    def _validate_spec_id(cls, value: str, info: ValidationInfo) -> str:
        """Validate optional ULID fields."""
        return _optional_ulid(value, field_name=info.field_name)


class ListEmbeddingsBySourceRequest(_ValidationModel):
    """Validated request shape for source-scoped embedding listing."""

    source_id: str
    spec_id: str

    @field_validator("source_id")
    @classmethod
    def _validate_source_id(cls, value: str, info: ValidationInfo) -> str:
        """Validate required ULID fields."""
        return _require_ulid(value, field_name=info.field_name)

    @field_validator("spec_id")
    @classmethod
    def _validate_spec_id(cls, value: str, info: ValidationInfo) -> str:
        """Validate optional ULID fields."""
        return _optional_ulid(value, field_name=info.field_name)


class ListEmbeddingsByStatusRequest(_ValidationModel):
    """Validated request shape for status-scoped embedding listing."""

    spec_id: str

    @field_validator("spec_id")
    @classmethod
    def _validate_spec_id(cls, value: str, info: ValidationInfo) -> str:
        """Validate optional ULID fields."""
        return _optional_ulid(value, field_name=info.field_name)


class SearchEmbeddingsRequest(_ValidationModel):
    """Validated request shape for semantic search operations."""

    query_vector: Sequence[float]
    source_id: str
    spec_id: str

    @field_validator("query_vector")
    @classmethod
    def _validate_query_vector(cls, value: Sequence[float]) -> Sequence[float]:
        """Require non-empty vectors."""
        if len(value) == 0:
            raise ValueError("query_vector is required")
        return value

    @field_validator("source_id", "spec_id")
    @classmethod
    def _validate_optional_ulids(cls, value: str, info: ValidationInfo) -> str:
        """Validate optional ULID filters."""
        return _optional_ulid(value, field_name=info.field_name)


class BatchChunkUpsertRequest(_ValidationModel):
    """Validated request shape for batch chunk upsert operations."""

    items: Sequence[UpsertChunkInput]

    @field_validator("items")
    @classmethod
    def _validate_items(
        cls, value: Sequence[UpsertChunkInput]
    ) -> Sequence[UpsertChunkInput]:
        """Require non-empty item sequences."""
        if len(value) == 0:
            raise ValueError("items must not be empty")
        return value


class BatchEmbeddingVectorUpsertRequest(_ValidationModel):
    """Validated request shape for batch vector upsert operations."""

    items: Sequence[UpsertEmbeddingVectorInput]

    @field_validator("items")
    @classmethod
    def _validate_items(
        cls, value: Sequence[UpsertEmbeddingVectorInput]
    ) -> Sequence[UpsertEmbeddingVectorInput]:
        """Require non-empty item sequences."""
        if len(value) == 0:
            raise ValueError("items must not be empty")
        return value
