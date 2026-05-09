"""Shared phone-number normalization helpers."""

from __future__ import annotations


def normalize_e164(*, raw: str, default_dial_code: str) -> str:
    """Normalize phone number input to canonical E.164 format."""
    candidate = raw.strip()
    if candidate == "":
        raise ValueError("phone number must be non-empty")

    dial_code = "".join(char for char in default_dial_code if char.isdigit())
    if dial_code == "":
        raise ValueError("default_dial_code must contain digits")

    digits = "".join(char for char in candidate if char.isdigit() or char == "+")
    if digits.startswith("+"):
        normalized = "+" + "".join(char for char in digits[1:] if char.isdigit())
    else:
        normalized_digits = "".join(char for char in digits if char.isdigit())
        if normalized_digits.startswith("00"):
            normalized_digits = normalized_digits[2:]
        else:
            if dial_code == "1" and len(normalized_digits) == 10:
                normalized_digits = f"1{normalized_digits}"
            elif not normalized_digits.startswith(dial_code):
                normalized_digits = f"{dial_code}{normalized_digits}"
        normalized = f"+{normalized_digits}"

    if not normalized.startswith("+"):
        raise ValueError("phone number must normalize to E.164")

    digits_only = normalized[1:]
    if len(digits_only) < 8 or len(digits_only) > 15:
        raise ValueError("phone number must contain 8-15 digits in E.164 form")
    if not digits_only.isdigit():
        raise ValueError("phone number must contain only digits after '+'")
    return normalized


__all__ = ["normalize_e164"]
