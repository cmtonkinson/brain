"""Tests for Ingestion Service extractor and normalizer registries."""

from __future__ import annotations

from typing import Sequence

from services.reason.ingestion.interfaces import (
    BaseExtractor,
    BaseNormalizer,
    ExtractedArtifact,
    ExtractorContext,
    ExtractorRegistry,
    NormalizedArtifact,
    NormalizerContext,
    NormalizerRegistry,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


def _make_extractor_context(mime_type: str | None = "text/plain") -> ExtractorContext:
    return ExtractorContext(
        ingestion_id="01HX0000000000000000000001",
        raw_object_key="raw/key.txt",
        payload=b"test content",
        mime_type=mime_type,
        source_type="test",
        source_uri=None,
        source_actor=None,
    )


def _make_normalizer_context(mime_type: str | None = "text/plain") -> NormalizerContext:
    return NormalizerContext(
        ingestion_id="01HX0000000000000000000001",
        extracted_object_key="extracted/key.txt",
        payload=b"extracted content",
        mime_type=mime_type,
        source_type="test",
        source_uri=None,
        source_actor=None,
    )


class _AlwaysExtractor(BaseExtractor):
    def can_extract(self, context: ExtractorContext) -> bool:
        return True

    def extract(self, context: ExtractorContext) -> Sequence[ExtractedArtifact]:
        return [
            ExtractedArtifact(
                payload=context.payload,
                mime_type=context.mime_type,
                method="always",
            )
        ]


class _NeverExtractor(BaseExtractor):
    def can_extract(self, context: ExtractorContext) -> bool:
        return False

    def extract(self, context: ExtractorContext) -> Sequence[ExtractedArtifact]:
        return []


class _TextOnlyExtractor(BaseExtractor):
    def can_extract(self, context: ExtractorContext) -> bool:
        return (context.mime_type or "").startswith("text/")

    def extract(self, context: ExtractorContext) -> Sequence[ExtractedArtifact]:
        return [
            ExtractedArtifact(
                payload=context.payload,
                mime_type=context.mime_type,
                method="text_only",
            )
        ]


class _AlwaysNormalizer(BaseNormalizer):
    def can_normalize(self, context: NormalizerContext) -> bool:
        return True

    def normalize(self, context: NormalizerContext) -> Sequence[NormalizedArtifact]:
        return [
            NormalizedArtifact(
                payload=context.payload,
                mime_type=context.mime_type,
                method="always",
            )
        ]


class _NeverNormalizer(BaseNormalizer):
    def can_normalize(self, context: NormalizerContext) -> bool:
        return False

    def normalize(self, context: NormalizerContext) -> Sequence[NormalizedArtifact]:
        return []


# ---------------------------------------------------------------------------
# ExtractorRegistry
# ---------------------------------------------------------------------------


class TestExtractorRegistry:
    def test_empty_registry_returns_no_matches(self) -> None:
        registry = ExtractorRegistry()
        ctx = _make_extractor_context()
        assert registry.match(ctx) == []

    def test_always_extractor_matches_any_context(self) -> None:
        registry = ExtractorRegistry([_AlwaysExtractor()])
        ctx = _make_extractor_context()
        assert len(registry.match(ctx)) == 1

    def test_never_extractor_matches_nothing(self) -> None:
        registry = ExtractorRegistry([_NeverExtractor()])
        ctx = _make_extractor_context()
        assert registry.match(ctx) == []

    def test_mixed_extractors_only_matching_returned(self) -> None:
        registry = ExtractorRegistry([_AlwaysExtractor(), _NeverExtractor()])
        ctx = _make_extractor_context()
        matched = registry.match(ctx)
        assert len(matched) == 1
        assert isinstance(matched[0], _AlwaysExtractor)

    def test_text_only_extractor_matches_text_mime(self) -> None:
        registry = ExtractorRegistry([_TextOnlyExtractor()])
        ctx = _make_extractor_context(mime_type="text/plain")
        assert len(registry.match(ctx)) == 1

    def test_text_only_extractor_does_not_match_pdf(self) -> None:
        registry = ExtractorRegistry([_TextOnlyExtractor()])
        ctx = _make_extractor_context(mime_type="application/pdf")
        assert registry.match(ctx) == []

    def test_register_adds_extractor_dynamically(self) -> None:
        registry = ExtractorRegistry()
        assert registry.match(_make_extractor_context()) == []
        registry.register(_AlwaysExtractor())
        assert len(registry.match(_make_extractor_context())) == 1

    def test_multiple_matching_extractors_all_returned(self) -> None:
        registry = ExtractorRegistry([_AlwaysExtractor(), _AlwaysExtractor()])
        ctx = _make_extractor_context()
        assert len(registry.match(ctx)) == 2

    def test_initialised_with_sequence(self) -> None:
        extractors = [_AlwaysExtractor(), _NeverExtractor(), _AlwaysExtractor()]
        registry = ExtractorRegistry(extractors)
        ctx = _make_extractor_context()
        assert len(registry.match(ctx)) == 2


# ---------------------------------------------------------------------------
# NormalizerRegistry
# ---------------------------------------------------------------------------


class TestNormalizerRegistry:
    def test_empty_registry_returns_no_matches(self) -> None:
        registry = NormalizerRegistry()
        ctx = _make_normalizer_context()
        assert registry.match(ctx) == []

    def test_always_normalizer_matches_any_context(self) -> None:
        registry = NormalizerRegistry([_AlwaysNormalizer()])
        ctx = _make_normalizer_context()
        assert len(registry.match(ctx)) == 1

    def test_never_normalizer_matches_nothing(self) -> None:
        registry = NormalizerRegistry([_NeverNormalizer()])
        ctx = _make_normalizer_context()
        assert registry.match(ctx) == []

    def test_mixed_normalizers_only_matching_returned(self) -> None:
        registry = NormalizerRegistry([_AlwaysNormalizer(), _NeverNormalizer()])
        ctx = _make_normalizer_context()
        matched = registry.match(ctx)
        assert len(matched) == 1
        assert isinstance(matched[0], _AlwaysNormalizer)

    def test_register_adds_normalizer_dynamically(self) -> None:
        registry = NormalizerRegistry()
        assert registry.match(_make_normalizer_context()) == []
        registry.register(_AlwaysNormalizer())
        assert len(registry.match(_make_normalizer_context())) == 1
