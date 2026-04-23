"""ULID conversion and generation helpers.

This module standardizes canonical big-endian ULID handling across the codebase.
The canonical string form is 26 Crockford Base32 characters representing exactly
128 bits.
"""

from __future__ import annotations

import ulid

ULID_BYTES_LENGTH = 16


def ulid_str_to_bytes(value: str) -> bytes:
    """Decode canonical 26-char ULID string into 16-byte big-endian form."""
    candidate = value.strip().upper()
    try:
        parsed = ulid.ULID.from_str(candidate)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    return parsed.bytes


def ulid_bytes_to_str(value: bytes) -> str:
    """Encode 16-byte big-endian ULID into canonical 26-char Base32 string."""
    if len(value) != ULID_BYTES_LENGTH:
        raise ValueError("ULID bytes must be exactly 16 bytes")
    return str(ulid.ULID.from_bytes(bytes(value)))


def generate_ulid_bytes(*, timestamp_ms: int | None = None) -> bytes:
    """Generate a new ULID as canonical 16-byte big-endian binary.

    Timestamp occupies the high 48 bits (milliseconds since epoch), and the
    remaining 80 bits are cryptographically secure random entropy.
    """
    if timestamp_ms is None:
        return ulid.ULID().bytes
    return ulid.ULID.from_timestamp(int(timestamp_ms)).bytes


def generate_ulid_str(*, timestamp_ms: int | None = None) -> str:
    """Generate a new ULID in canonical 26-char string format."""
    return ulid_bytes_to_str(generate_ulid_bytes(timestamp_ms=timestamp_ms))


def require_ulid_bytes(value: object, *, field_name: str = "id") -> bytes:
    """Validate and normalize a value as canonical 16-byte ULID binary."""
    if isinstance(value, (bytes, bytearray)) and len(value) == ULID_BYTES_LENGTH:
        return bytes(value)
    raise ValueError(f"{field_name} must be 16-byte ULID binary")
