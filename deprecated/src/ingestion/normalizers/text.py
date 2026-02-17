"""Default text normalizer for Stage 3."""

from __future__ import annotations

from typing import Sequence

from . import BaseNormalizer, NormalizedArtifact, NormalizerContext


class DefaultTextNormalizer(BaseNormalizer):
    """Simple normalizer that trims noise from plain text payloads."""

    _NOISE_MARKERS = ("advertisement", "ad:", "[ad]", "nav")

    def can_normalize(self, context: NormalizerContext) -> bool:
        """Only normalize when the payload is text based."""
        return context.mime_type in {"text/plain", "text/markdown", None}

    def normalize(self, context: NormalizerContext) -> Sequence[NormalizedArtifact]:
        """Strip boilerplate, collapse blank lines, and surface Markdown content."""
        decoded = context.payload.decode("utf-8", errors="replace")
        lines: list[str] = []
        last_blank = False
        for raw_line in decoded.splitlines():
            stripped = raw_line.strip()
            if not stripped:
                if last_blank:
                    continue
                lines.append("")
                last_blank = True
                continue
            normalized = stripped
            lower = normalized.lower()
            if any(marker in lower for marker in self._NOISE_MARKERS):
                continue
            lines.append(normalized)
            last_blank = False
        normalized_text = "\n".join(lines).strip()
        if not normalized_text:
            normalized_text = decoded.strip()
        return [
            NormalizedArtifact(
                payload=normalized_text.encode("utf-8"),
                mime_type="text/markdown",
                method="canonical_markdown",
                confidence=0.75,
                tool_metadata={
                    "filters": ["ad", "nav"],
                    "source_type": context.source_type,
                    "extracted_object_key": context.extracted_object_key,
                },
            )
        ]
