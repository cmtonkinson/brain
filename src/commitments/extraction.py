"""LLM-based commitment extraction from text content."""

from __future__ import annotations

import json
import logging
from typing import Any

from llm import LLMClient

LOGGER = logging.getLogger(__name__)

EXTRACTION_PROMPT = """Extract any commitments, promises, or action items from the following text.

A commitment is something the person has agreed to do, promised to complete, or needs to take action on.

For each commitment found, extract:
- description: Clear, concise description of what needs to be done
- due_by: Due date if mentioned (ISO 8601 format, or null if not specified)
- importance: 1 (low), 2 (medium), or 3 (high) - infer from context
- effort_provided: 1 (small), 2 (medium), or 3 (large) - estimate effort required
- confidence: 0.0 to 1.0 - how confident you are this is actually a commitment

Return a JSON array of commitments. If no commitments are found, return an empty array.

Text to analyze:
{text}

Response format:
[
  {{
    "description": "Review the quarterly report",
    "due_by": "2026-02-10T17:00:00Z",
    "importance": 2,
    "effort_provided": 2,
    "confidence": 0.85
  }}
]
"""


def extract_commitments_from_text(
    text: str,
    *,
    client: LLMClient | None = None,
) -> list[dict[str, Any]]:
    """Extract commitments from text using LLM analysis.

    Args:
        text: The text content to analyze
        client: Optional LLM client (if None, extraction is skipped)

    Returns:
        List of commitment dictionaries with keys:
        - description (str): What needs to be done
        - due_by (str | None): ISO 8601 due date if specified
        - importance (int): 1-3
        - effort_provided (int): 1-3
        - confidence (float): 0.0-1.0
    """
    if not text or not text.strip():
        LOGGER.debug("Empty text provided, skipping extraction")
        return []

    if client is None:
        LOGGER.debug("No LLM client provided, skipping extraction")
        return []

    # Truncate very long text to avoid token limits
    max_chars = 8000
    if len(text) > max_chars:
        LOGGER.info("Truncating text from %s to %s chars for extraction", len(text), max_chars)
        text = text[:max_chars] + "\n\n[... truncated ...]"

    try:
        prompt = EXTRACTION_PROMPT.format(text=text)
        response = client.generate(prompt)

        # Parse JSON response
        response_text = response.strip()

        # Handle markdown code blocks
        if response_text.startswith("```"):
            # Extract content between ``` blocks
            lines = response_text.split("\n")
            response_text = "\n".join(lines[1:-1]) if len(lines) > 2 else response_text
            # Remove language identifier if present
            if response_text.startswith("json"):
                response_text = response_text[4:].strip()

        commitments = json.loads(response_text)

        if not isinstance(commitments, list):
            LOGGER.warning("LLM returned non-list response: %s", type(commitments))
            return []

        # Validate and normalize each commitment
        validated = []
        for commitment in commitments:
            if not isinstance(commitment, dict):
                LOGGER.warning("Skipping non-dict commitment: %s", commitment)
                continue

            # Ensure required fields
            if "description" not in commitment or not commitment["description"]:
                LOGGER.warning("Skipping commitment without description: %s", commitment)
                continue

            # Normalize fields
            normalized = {
                "description": str(commitment["description"]).strip(),
                "due_by": commitment.get("due_by"),
                "importance": _normalize_int(commitment.get("importance", 2), 1, 3, default=2),
                "effort_provided": _normalize_int(commitment.get("effort_provided", 2), 1, 3, default=2),
                "confidence": _normalize_float(commitment.get("confidence", 0.5), 0.0, 1.0, default=0.5),
            }

            validated.append(normalized)

        LOGGER.info("Extracted %s commitment(s) from text", len(validated))
        return validated

    except json.JSONDecodeError as e:
        LOGGER.error("Failed to parse LLM response as JSON: %s", e)
        LOGGER.debug("LLM response was: %s", response[:500] if 'response' in locals() else 'N/A')
        return []
    except Exception as e:
        LOGGER.exception("Unexpected error during commitment extraction: %s", e)
        return []


def _normalize_int(value: Any, min_val: int, max_val: int, default: int) -> int:
    """Normalize a value to an integer within bounds."""
    try:
        int_val = int(value)
        return max(min_val, min(max_val, int_val))
    except (TypeError, ValueError):
        return default


def _normalize_float(value: Any, min_val: float, max_val: float, default: float) -> float:
    """Normalize a value to a float within bounds."""
    try:
        float_val = float(value)
        return max(min_val, min(max_val, float_val))
    except (TypeError, ValueError):
        return default


__all__ = ["extract_commitments_from_text"]
