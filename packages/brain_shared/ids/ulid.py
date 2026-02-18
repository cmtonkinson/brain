"""ULID conversion and generation helpers.

This module standardizes canonical big-endian ULID handling across the codebase.
The canonical string form is 26 Crockford Base32 characters representing exactly
128 bits.
"""

from __future__ import annotations

import secrets
import time

_ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_DECODE_TABLE = {char: index for index, char in enumerate(_ULID_ALPHABET)}
_MAX_ULID_INT = (1 << 128) - 1


def ulid_str_to_bytes(value: str) -> bytes:
    """Decode canonical 26-char ULID string into 16-byte big-endian form."""
    candidate = value.strip().upper()
    if len(candidate) != 26:
        raise ValueError("ULID string must be exactly 26 characters")

    number = 0
    for char in candidate:
        if char not in _DECODE_TABLE:
            raise ValueError(f"Invalid ULID character: {char!r}")
        number = (number << 5) | _DECODE_TABLE[char]

    # 26 base32 chars encode 130 bits; canonical ULID uses only lower 128 bits.
    if number > _MAX_ULID_INT:
        raise ValueError("ULID value exceeds 128-bit range")
    return number.to_bytes(16, byteorder="big", signed=False)


def ulid_bytes_to_str(value: bytes) -> str:
    """Encode 16-byte big-endian ULID into canonical 26-char Base32 string."""
    if len(value) != 16:
        raise ValueError("ULID bytes must be exactly 16 bytes")

    number = int.from_bytes(value, byteorder="big", signed=False)
    chars: list[str] = []
    for _ in range(26):
        number, remainder = divmod(number, 32)
        chars.append(_ULID_ALPHABET[remainder])
    return "".join(reversed(chars))


def generate_ulid_bytes(*, timestamp_ms: int | None = None) -> bytes:
    """Generate a new ULID as canonical 16-byte big-endian binary.

    Timestamp occupies the high 48 bits (milliseconds since epoch), and the
    remaining 80 bits are cryptographically secure random entropy.
    """
    ts_ms = int(time.time() * 1000) if timestamp_ms is None else int(timestamp_ms)
    if ts_ms < 0 or ts_ms >= (1 << 48):
        raise ValueError("timestamp_ms out of ULID 48-bit range")

    entropy = int.from_bytes(secrets.token_bytes(10), byteorder="big", signed=False)
    number = (ts_ms << 80) | entropy
    return number.to_bytes(16, byteorder="big", signed=False)


def generate_ulid_str(*, timestamp_ms: int | None = None) -> str:
    """Generate a new ULID in canonical 26-char string format."""
    return ulid_bytes_to_str(generate_ulid_bytes(timestamp_ms=timestamp_ms))


def require_ulid_bytes(value: object, *, field_name: str = "id") -> bytes:
    """Validate and normalize a value as canonical 16-byte ULID binary."""
    if isinstance(value, (bytes, bytearray)) and len(value) == 16:
        return bytes(value)
    raise ValueError(f"{field_name} must be 16-byte ULID binary")
