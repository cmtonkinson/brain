"""Real-provider integration tests for CES Postgres audit repository."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from services.action.capability_engine.data.repository import (
    PostgresCapabilityInvocationAuditRepository,
)
from services.action.capability_engine.data.runtime import (
    CapabilityEnginePostgresRuntime,
)
from services.action.capability_engine.domain import CapabilityInvocationAuditRow
from tests.integration.helpers import real_provider_tests_enabled

pytest_plugins = ("tests.integration.fixtures",)


pytestmark = pytest.mark.skipif(
    not real_provider_tests_enabled(),
    reason="set BRAIN_RUN_INTEGRATION_REAL=1 to run real-provider integration tests",
)


def test_append_and_count_roundtrip(migrated_integration_settings) -> None:
    """Repository should append audit rows and increment count."""
    runtime = CapabilityEnginePostgresRuntime.from_settings(
        migrated_integration_settings
    )
    repo = PostgresCapabilityInvocationAuditRepository(runtime.schema_sessions)

    before = repo.count()
    row = CapabilityInvocationAuditRow(
        audit_id="",
        envelope_id="env-int",
        trace_id="trace-int",
        parent_id="",
        invocation_id="inv-int",
        parent_invocation_id="",
        actor="operator",
        source="test",
        channel="signal",
        capability_id="demo",
        capability_version="1.0.0",
        policy_decision_id="decision-int",
        policy_regime_id="regime-int",
        allowed=True,
        reason_codes=(),
        proposal_token="",
        created_at=datetime.now(UTC),
    )
    repo.append(row=row)

    assert repo.count() >= before + 1
