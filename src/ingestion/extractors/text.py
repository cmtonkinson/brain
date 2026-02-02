"""Plain text extractor implementations for Stage 2."""

from __future__ import annotations

from . import BaseExtractor, ExtractedArtifact, ExtractorContext


class TextExtractor(BaseExtractor):
    """Minimal extractor that produces readable text outputs."""

    def can_extract(self, context: ExtractorContext) -> bool:
        """Only handle artifacts explicitly marked as text/plain."""
        return context.mime_type == "text/plain"

    def extract(self, context: ExtractorContext) -> list[ExtractedArtifact]:
        """Return the normalized text bytes as a single extracted artifact."""
        normalized = b"text-extracted:" + context.payload
        return [
            ExtractedArtifact(
                payload=normalized,
                mime_type="text/plain",
                method="text/plain",
            )
        ]
