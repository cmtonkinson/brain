"""Real-provider integration tests for Policy Service Postgres repository."""

from __future__ import annotations

import pytest

from packages.brain_shared.ids import generate_ulid_str
from services.action.policy_service.data.repository import (
    PostgresPolicyPersistenceRepository,
)
from services.action.policy_service.data.runtime import PolicyServicePostgresRuntime
from services.action.policy_service.domain import PolicyRegimeSnapshot, utc_now
from tests.integration.helpers import real_provider_tests_enabled

pytest_plugins = ("tests.integration.fixtures",)


pytestmark = pytest.mark.skipif(
    not real_provider_tests_enabled(),
    reason="set BRAIN_RUN_INTEGRATION_REAL=1 to run real-provider integration tests",
)


def test_policy_regime_and_active_pointer_roundtrip(
    migrated_integration_settings,
) -> None:
    """Repository should upsert one regime and persist active pointer."""
    runtime = PolicyServicePostgresRuntime.from_settings(migrated_integration_settings)
    repo = PostgresPolicyPersistenceRepository(runtime.schema_sessions)

    snapshot = PolicyRegimeSnapshot(
        policy_regime_id=generate_ulid_str(),
        policy_hash=f"h-{generate_ulid_str()}",
        policy_json='{"policy_id":"p","policy_version":"1","rules":{}}',
        policy_id="p",
        policy_version="1",
        created_at=utc_now(),
    )
    persisted = repo.upsert_policy_regime(snapshot=snapshot)
    repo.set_active_policy_regime(policy_regime_id=persisted.policy_regime_id)

    assert repo.get_active_policy_regime_id() == persisted.policy_regime_id
    assert any(
        item.policy_hash == snapshot.policy_hash for item in repo.list_policy_regimes()
    )
