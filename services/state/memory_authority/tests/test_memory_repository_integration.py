"""Real-provider integration tests for MAS Postgres repository."""

from __future__ import annotations

import pytest

from services.state.memory_authority.data.repository import PostgresMemoryRepository
from services.state.memory_authority.data.runtime import MemoryPostgresRuntime
from services.state.memory_authority.domain import TurnDirection
from tests.integration.helpers import real_provider_tests_enabled

pytest_plugins = ("tests.integration.fixtures",)


pytestmark = pytest.mark.skipif(
    not real_provider_tests_enabled(),
    reason="set BRAIN_RUN_INTEGRATION_REAL=1 to run real-provider integration tests",
)


def test_session_turn_and_summary_roundtrip(migrated_integration_settings) -> None:
    """Repository should persist sessions and turns with stable ordering."""
    runtime = MemoryPostgresRuntime.from_settings(migrated_integration_settings)
    repo = PostgresMemoryRepository(runtime.schema_sessions)

    session = repo.create_session()
    first = repo.insert_turn(
        session_id=session.id,
        direction=TurnDirection.INBOUND,
        content="hello",
        role="user",
        model=None,
        provider=None,
        token_count=None,
        reasoning_level=None,
        trace_id="trace-1",
        principal="operator",
    )
    second = repo.insert_turn(
        session_id=session.id,
        direction=TurnDirection.OUTBOUND,
        content="world",
        role="assistant",
        model="gpt-oss",
        provider="ollama",
        token_count=3,
        reasoning_level="standard",
        trace_id="trace-1",
        principal="operator",
    )

    turns = repo.list_turns(session_id=session.id)
    assert [item.id for item in turns][:2] == [first.id, second.id]
