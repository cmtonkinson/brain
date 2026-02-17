"""Extractor plumbing for Stage 2 fan-out."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, Sequence
from uuid import UUID


@dataclass(frozen=True)
class ExtractorContext:
    """Artifact context supplied to extractor implementations."""

    ingestion_id: UUID
    raw_object_key: str
    payload: bytes
    mime_type: str | None
    source_type: str
    source_uri: str | None
    source_actor: str | None


@dataclass(frozen=True)
class ExtractedArtifact:
    """Descriptor for a derived artifact produced by an extractor."""

    payload: bytes
    mime_type: str | None
    method: str
    confidence: float | None = None
    page_count: int | None = None
    tool_metadata: dict[str, object] | None = None


class BaseExtractor(ABC):
    """Abstract base class for Stage 2 extractor implementations."""

    @abstractmethod
    def can_extract(self, context: ExtractorContext) -> bool:
        """Return True if this extractor can handle the provided context."""

    @abstractmethod
    def extract(self, context: ExtractorContext) -> Sequence[ExtractedArtifact]:
        """Produce extracted artifacts derived from the given context."""


class ExtractorRegistry:
    """Registry that matches extractors against incoming artifacts."""

    def __init__(self, extractors: Iterable[BaseExtractor]) -> None:
        """Initialize the registry with a sequence of extractor instances."""
        self._extractors = list(extractors)

    def match(self, context: ExtractorContext) -> list[BaseExtractor]:
        """Return extractors that can process the supplied context."""
        return [extractor for extractor in self._extractors if extractor.can_extract(context)]
