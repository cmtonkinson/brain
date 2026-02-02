"""Shared constants for the ingestion pipeline."""

from __future__ import annotations

from typing import Sequence

STAGE_ORDER: Sequence[str] = ("store", "extract", "normalize", "anchor")
"""Ordered ingestion stages used across services."""

STAGE_SET = frozenset(STAGE_ORDER)
"""Fast membership set for known ingestion stages."""
