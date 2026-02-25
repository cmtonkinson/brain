"""Unit tests for Policy Service data schema definitions."""

from __future__ import annotations

from services.action.policy_service.data.schema import (
    active_policy_regime,
    approvals,
    policy_decisions,
    policy_dedupe_logs,
    policy_regimes,
)


def test_policy_regime_schema_contains_required_columns() -> None:
    columns = set(policy_regimes.c.keys())
    assert {"id", "policy_hash", "policy_json", "policy_id", "policy_version"}.issubset(
        columns
    )


def test_active_pointer_schema_contains_required_columns() -> None:
    columns = set(active_policy_regime.c.keys())
    assert {"pointer_id", "policy_regime_id"}.issubset(columns)


def test_policy_decision_schema_contains_required_columns() -> None:
    columns = set(policy_decisions.c.keys())
    assert {
        "policy_regime_id",
        "envelope_id",
        "trace_id",
        "actor",
        "channel",
        "capability_id",
        "proposal_token",
    }.issubset(columns)


def test_approval_schema_contains_required_columns() -> None:
    columns = set(approvals.c.keys())
    assert {
        "proposal_token",
        "policy_regime_id",
        "capability_id",
        "capability_version",
        "summary",
        "trace_id",
        "invocation_id",
        "status",
        "clarification_attempts",
    }.issubset(columns)


def test_policy_dedupe_schema_contains_required_columns() -> None:
    columns = set(policy_dedupe_logs.c.keys())
    assert {
        "dedupe_key",
        "envelope_id",
        "trace_id",
        "denied",
        "window_seconds",
    }.issubset(columns)
