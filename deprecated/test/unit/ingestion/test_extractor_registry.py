"""Unit tests for the Stage 2 extractor registry."""

from uuid import uuid4

from ingestion.extractors import ExtractorContext, ExtractorRegistry
from ingestion.extractors.text import TextExtractor


def _build_context(mime_type: str | None) -> ExtractorContext:
    """Build a minimal extractor context for testing."""
    return ExtractorContext(
        ingestion_id=uuid4(),
        raw_object_key="b1:sha256:" + "0" * 64,
        payload=b"text",
        mime_type=mime_type,
        source_type="signal",
        source_uri=None,
        source_actor=None,
    )


def test_registry_selects_text_extractor() -> None:
    """Plain text artifacts should match the TextExtractor."""
    registry = ExtractorRegistry([TextExtractor()])
    context = _build_context("text/plain")

    matches = registry.match(context)

    assert len(matches) == 1
    assert isinstance(matches[0], TextExtractor)


def test_registry_returns_empty_for_unknown_mime() -> None:
    """Unsupported mime types should not raise but return an empty list."""
    registry = ExtractorRegistry([TextExtractor()])
    context = _build_context("image/png")

    matches = registry.match(context)

    assert matches == []
