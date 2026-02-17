"""Normalizer plumbing for Stage 3 canonicalization."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, Sequence
from uuid import UUID


@dataclass(frozen=True)
class ExtractionMetadataSnapshot:
    """Snapshot of extraction metadata supplied to normalizers."""

    method: str | None = None
    confidence: float | None = None
    page_count: int | None = None
    tool_metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class NormalizerContext:
    """Normalized context supplied to each normalizer implementation."""

    ingestion_id: UUID
    extracted_object_key: str
    payload: bytes
    mime_type: str | None
    source_type: str
    source_uri: str | None
    source_actor: str | None
    extraction_metadata: ExtractionMetadataSnapshot | None = None


@dataclass(frozen=True)
class NormalizedArtifact:
    """Descriptor for canonical output produced by a normalizer."""

    payload: bytes
    mime_type: str | None
    method: str
    confidence: float | None = None
    tool_metadata: dict[str, object] | None = None


class BaseNormalizer(ABC):
    """Base interface for Stage 3 normalizers."""

    @abstractmethod
    def can_normalize(self, context: NormalizerContext) -> bool:
        """Return True when this normalizer can handle the provided context."""

    @abstractmethod
    def normalize(self, context: NormalizerContext) -> Sequence[NormalizedArtifact]:
        """Produce canonical artifacts derived from the provided context."""


class NormalizerRegistry:
    """Registry that matches available normalizers against extracted artifacts."""

    def __init__(self, normalizers: Iterable[BaseNormalizer]) -> None:
        """Initialize the registry with a sequence of normalizer instances."""
        self._normalizers = list(normalizers)

    def match(self, context: NormalizerContext) -> list[BaseNormalizer]:
        """Return the subset of normalizers that can handle the supplied context."""
        return [normalizer for normalizer in self._normalizers if normalizer.can_normalize(context)]


__all__ = [
    "ExtractionMetadataSnapshot",
    "NormalizerContext",
    "NormalizedArtifact",
    "BaseNormalizer",
    "NormalizerRegistry",
]
