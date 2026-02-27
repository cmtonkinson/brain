"""Unit tests for Brain SDK metadata helpers."""

from __future__ import annotations

from datetime import datetime


def test_build_envelope_meta_sets_defaults() -> None:
    """Metadata builder should generate ids, UTC timestamp, and command kind."""
    from packages.brain_sdk.meta import build_envelope_meta

    meta = build_envelope_meta(source="cli", principal="operator")

    assert meta["envelope_id"] != ""
    assert meta["trace_id"] != ""
    assert meta["kind"] == "command"
    assert meta["source"] == "cli"
    assert meta["principal"] == "operator"
    assert "T" in meta["timestamp"]  # ISO format contains T separator


def test_build_envelope_meta_respects_overrides() -> None:
    """Metadata builder should preserve caller-provided trace/parent/timestamp."""
    from packages.brain_sdk.meta import build_envelope_meta

    timestamp = datetime(2026, 2, 26, 15, 0, 0)
    meta = build_envelope_meta(
        source="agent",
        principal="core",
        trace_id="trace-123",
        parent_id="parent-456",
        envelope_id="envelope-789",
        timestamp=timestamp,
    )

    assert meta["trace_id"] == "trace-123"
    assert meta["parent_id"] == "parent-456"
    assert meta["envelope_id"] == "envelope-789"
    assert "2026-02-26" in meta["timestamp"]
