"""Tests for Ingestion Service submission validation helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from services.reason.ingestion.implementation import (
    _parse_capture_time,
    _validate_submission,
)


# ---------------------------------------------------------------------------
# _parse_capture_time
# ---------------------------------------------------------------------------


class TestParseCaptureTime:
    def test_valid_utc_offset(self) -> None:
        dt, err = _parse_capture_time("2026-01-15T10:30:00+00:00")
        assert err is None
        assert dt is not None
        assert dt.tzinfo is UTC

    def test_valid_z_suffix(self) -> None:
        dt, err = _parse_capture_time("2026-01-15T10:30:00Z")
        assert err is None
        assert dt is not None
        assert dt.tzinfo is UTC

    def test_valid_non_utc_offset_normalized_to_utc(self) -> None:
        dt, err = _parse_capture_time("2026-01-15T12:30:00+02:00")
        assert err is None
        assert dt is not None
        assert dt.tzinfo is UTC
        assert dt.hour == 10

    def test_naive_datetime_rejected(self) -> None:
        dt, err = _parse_capture_time("2026-01-15T10:30:00")
        assert dt is None
        assert err is not None
        assert "timezone-aware" in err

    def test_empty_string_rejected(self) -> None:
        dt, err = _parse_capture_time("")
        assert dt is None
        assert err is not None
        assert "required" in err

    def test_whitespace_only_rejected(self) -> None:
        dt, err = _parse_capture_time("   ")
        assert dt is None
        assert err is not None

    def test_invalid_format_rejected(self) -> None:
        dt, err = _parse_capture_time("not-a-date")
        assert dt is None
        assert err is not None
        assert "ISO 8601" in err

    def test_date_only_rejected(self) -> None:
        # date-only strings parse without time, no tz — expect error
        dt, err = _parse_capture_time("2026-01-15")
        # fromisoformat("2026-01-15") succeeds but is naive
        assert dt is None
        assert err is not None

    def test_returns_utc_aware_datetime(self) -> None:
        dt, err = _parse_capture_time("2026-06-01T00:00:00Z")
        assert err is None
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 6
        assert dt.day == 1


# ---------------------------------------------------------------------------
# _validate_submission
# ---------------------------------------------------------------------------


class TestValidateSubmission:
    _VALID_TS = datetime(2026, 1, 1, tzinfo=UTC)
    _MAX_BYTES = 10_485_760  # 10 MiB

    def _call(
        self,
        *,
        source_type: str = "test_source",
        payload: bytes | None = b"hello",
        existing_object_key: str | None = None,
        capture_time: datetime | None = None,
        max_payload_bytes: int | None = None,
    ):
        return _validate_submission(
            source_type=source_type,
            payload=payload,
            existing_object_key=existing_object_key,
            capture_time=capture_time or self._VALID_TS,
            max_payload_bytes=max_payload_bytes or self._MAX_BYTES,
        )

    def test_valid_payload_submission(self) -> None:
        errors = self._call()
        assert errors == []

    def test_valid_existing_key_submission(self) -> None:
        errors = self._call(payload=None, existing_object_key="abc/key.bin")
        assert errors == []

    def test_missing_source_type(self) -> None:
        errors = self._call(source_type="")
        assert any("source_type" in e.message for e in errors)

    def test_whitespace_source_type(self) -> None:
        errors = self._call(source_type="   ")
        assert any("source_type" in e.message for e in errors)

    def test_both_payload_and_existing_key_rejected(self) -> None:
        errors = self._call(payload=b"data", existing_object_key="abc/key.bin")
        assert any("exactly one" in e.message for e in errors)

    def test_neither_payload_nor_existing_key_rejected(self) -> None:
        errors = self._call(payload=None, existing_object_key=None)
        assert any("exactly one" in e.message for e in errors)

    def test_payload_exceeds_max_size(self) -> None:
        too_large = b"x" * 101
        errors = self._call(payload=too_large, max_payload_bytes=100)
        assert any("maximum size" in e.message for e in errors)

    def test_payload_exactly_at_max_size_is_allowed(self) -> None:
        exact = b"x" * 100
        errors = self._call(payload=exact, max_payload_bytes=100)
        assert errors == []

    def test_multiple_errors_returned(self) -> None:
        errors = self._call(
            source_type="",
            payload=None,
            existing_object_key=None,
        )
        # both source_type and exactly-one errors should be present
        assert len(errors) >= 2

    def test_empty_payload_not_exceeding_max(self) -> None:
        errors = self._call(payload=b"")
        assert errors == []
