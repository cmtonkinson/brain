"""Real-provider integration tests for OAS Postgres repository."""

from __future__ import annotations

import pytest

from services.state.object_authority.data.repository import PostgresObjectRepository
from services.state.object_authority.data.runtime import ObjectPostgresRuntime
from tests.integration.helpers import real_provider_tests_enabled

pytest_plugins = ("tests.integration.fixtures",)


pytestmark = pytest.mark.skipif(
    not real_provider_tests_enabled(),
    reason="set BRAIN_RUN_INTEGRATION_REAL=1 to run real-provider integration tests",
)


def test_upsert_get_delete_roundtrip(migrated_integration_settings) -> None:
    """Repository should upsert one object metadata row and delete by key."""
    runtime = ObjectPostgresRuntime.from_settings(migrated_integration_settings)
    repo = PostgresObjectRepository(runtime.schema_sessions)

    key = "b1:sha256:1111111111111111111111111111111111111111111111111111111111111111"
    record = repo.upsert_object(
        object_key=key,
        digest_algorithm="sha256",
        digest_version="b1",
        digest_hex="1111111111111111111111111111111111111111111111111111111111111111",
        extension="txt",
        content_type="text/plain",
        size_bytes=4,
        original_filename="x.txt",
        source_uri="test://x",
    )

    fetched = repo.get_object_by_key(object_key=record.ref.object_key)
    assert fetched is not None
    assert repo.delete_object_by_key(object_key=record.ref.object_key) is True
