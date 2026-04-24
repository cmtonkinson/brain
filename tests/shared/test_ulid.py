"""Tests for shared ULID conversion and ordering semantics."""

from __future__ import annotations

import pytest

from lib.shared.ids import (
    generate_ulid_bytes,
    generate_ulid_str,
    require_ulid_bytes,
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


# ---------------------------------------------------------------------------
# ulid_str_to_bytes edge cases
# ---------------------------------------------------------------------------


def test_ulid_str_to_bytes_rejects_invalid_string() -> None:
    """Non-ULID strings should raise ValueError."""
    with pytest.raises(ValueError):
        ulid_str_to_bytes("not-a-ulid")


def test_ulid_str_to_bytes_rejects_wrong_length() -> None:
    """Strings that are not 26 characters should be rejected."""
    with pytest.raises(ValueError):
        ulid_str_to_bytes("01ARZ3NDEKTSV4RRFFQ69G5FA")  # 25 chars


# ---------------------------------------------------------------------------
# ulid_bytes_to_str edge cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("length", [0, 15, 17])
def test_ulid_bytes_to_str_rejects_wrong_length_bytes(length: int) -> None:
    """Byte sequences that are not exactly 16 bytes should be rejected."""
    with pytest.raises(ValueError, match="exactly 16 bytes"):
        ulid_bytes_to_str(b"\x00" * length)


# ---------------------------------------------------------------------------
# require_ulid_bytes
# ---------------------------------------------------------------------------


def test_require_ulid_bytes_accepts_valid_16_byte_input() -> None:
    """16-byte binary should be accepted and returned as bytes."""
    raw = generate_ulid_bytes()
    assert require_ulid_bytes(raw) == raw
    assert isinstance(require_ulid_bytes(raw), bytes)


def test_require_ulid_bytes_accepts_bytearray() -> None:
    """16-byte bytearray should be accepted and returned as bytes."""
    raw = bytearray(generate_ulid_bytes())
    result = require_ulid_bytes(raw)
    assert isinstance(result, bytes)
    assert len(result) == 16


def test_require_ulid_bytes_rejects_wrong_length() -> None:
    """Byte sequences shorter or longer than 16 should be rejected."""
    with pytest.raises(ValueError, match="16-byte ULID"):
        require_ulid_bytes(b"\x00" * 15)


@pytest.mark.parametrize("value", ["not-bytes", 42, [1, 2, 3]])
def test_require_ulid_bytes_rejects_non_bytes_types(value: object) -> None:
    """Non-bytes/bytearray types should be rejected with field name in message."""
    with pytest.raises(ValueError, match="id"):
        require_ulid_bytes(value)


# ---------------------------------------------------------------------------
# generate_ulid_str format
# ---------------------------------------------------------------------------


def test_generate_ulid_str_returns_26_char_crockford_base32() -> None:
    """Generated ULID string should be 26 chars of valid Crockford Base32."""
    value = generate_ulid_str()
    assert len(value) == 26
    valid_chars = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")
    assert all(c in valid_chars for c in value)
