"""Unit tests for Capability Engine data schema definitions."""

from __future__ import annotations

from services.action.capability_engine.data.schema import invocation_audits


def test_invocation_audit_schema_contains_required_columns() -> None:
    columns = set(invocation_audits.c.keys())
    assert "envelope_id" in columns
    assert "trace_id" in columns
    assert "parent_id" in columns
    assert "capability_id" in columns
    assert "policy_decision_id" in columns
    assert "policy_regime_id" in columns
    assert "allowed" in columns
    assert "reason_codes" in columns
