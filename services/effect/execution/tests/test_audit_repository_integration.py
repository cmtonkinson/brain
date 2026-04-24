"""Real-provider integration tests for Execution Postgres audit repository."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from services.effect.execution.data.repository import (
    PostgresOpInvocationAuditRepository,
)
from services.effect.execution.data.runtime import (
    ExecutionPostgresRuntime,
)
from services.effect.execution.domain import OpInvocationAuditRow
from tests.integration.helpers import real_provider_tests_enabled

pytest_plugins = ("tests.integration.fixtures",)


pytestmark = pytest.mark.skipif(
    not real_provider_tests_enabled(),
    reason="set BRAIN_RUN_INTEGRATION_REAL=1 to run real-provider integration tests",
)


def test_append_and_count_roundtrip(migrated_integration_settings) -> None:
    """Repository should append audit rows and increment count."""
    runtime = ExecutionPostgresRuntime.from_settings(migrated_integration_settings)
    repo = PostgresOpInvocationAuditRepository(runtime.schema_sessions)

    before = repo.count()
    row = OpInvocationAuditRow(
        audit_id="",
        envelope_id="env-int",
        trace_id="trace-int",
        parent_id="",
        invocation_id="inv-int",
        parent_invocation_id="",
        actor="operator",
        source="test",
        channel="signal",
        op_id="demo",
        op_version="1.0.0",
        policy_decision_id="decision-int",
        policy_regime_id="regime-int",
        allowed=True,
        reason_codes=(),
        proposal_token="",
        created_at=datetime.now(UTC),
    )
    repo.append(row=row)

    assert repo.count() >= before + 1
