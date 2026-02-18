"""Tests for shared ULID conversion and ordering semantics."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.brain_shared.ids import (
    generate_ulid_bytes,
    generate_ulid_str,
    ulid_bytes_to_str,
    ulid_str_to_bytes,
)


def test_ulid_round_trip_string_bytes_string() -> None:
    """ULID string/bytes conversion must be lossless."""
    ulid_value = generate_ulid_str()
    encoded = ulid_str_to_bytes(ulid_value)
    decoded = ulid_bytes_to_str(encoded)
    assert decoded == ulid_value


def test_ulid_round_trip_bytes_string_bytes() -> None:
    """ULID bytes/string conversion must be lossless."""
    ulid_value = generate_ulid_bytes()
    encoded = ulid_bytes_to_str(ulid_value)
    decoded = ulid_str_to_bytes(encoded)
    assert decoded == ulid_value


def test_ulid_lexicographic_order_matches_big_endian_binary() -> None:
    """Sorting canonical strings must match sorting binary big-endian ULIDs."""
    # Fix timestamp to remove time-based drift and compare entropy ordering only.
    values = [generate_ulid_bytes(timestamp_ms=1_700_000_000_000) for _ in range(300)]

    sorted_by_binary = sorted(values)
    sorted_by_string = sorted(values, key=ulid_bytes_to_str)

    assert sorted_by_binary == sorted_by_string
