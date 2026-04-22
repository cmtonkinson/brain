"""Real-provider integration tests for MAS Postgres repository."""

from __future__ import annotations

import pytest

from services.state.memory_authority.data.repository import PostgresMemoryRepository
from services.state.memory_authority.data.runtime import MemoryPostgresRuntime
from services.state.memory_authority.domain import (
    InboundInstructionRecord,
    OutboundDeliveryRecord,
    TurnDirection,
)
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
    assert session.current_conversation_episode_id not in (None, "")
    assert session.last_episode_inbound_at is None
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
        conversation_episode_id="episode-1",
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
        conversation_episode_id="episode-1",
        principal="operator",
    )

    turns = repo.list_turns(session_id=session.id)
    assert [item.id for item in turns][:2] == [first.id, second.id]


def test_turn_metadata_and_delivery_roundtrip(migrated_integration_settings) -> None:
    """Repository should persist inbound metadata and outbound delivery updates."""
    runtime = MemoryPostgresRuntime.from_settings(migrated_integration_settings)
    repo = PostgresMemoryRepository(runtime.schema_sessions)

    session = repo.create_session()
    inbound = repo.insert_turn(
        session_id=session.id,
        direction=TurnDirection.INBOUND,
        content="hello",
        role="user",
        model=None,
        provider=None,
        token_count=None,
        reasoning_level=None,
        trace_id="trace-2",
        conversation_episode_id="episode-2",
        principal="operator",
        source="signal",
        instruction=InboundInstructionRecord(
            sender_e164="+12025550100",
            message_text="hello",
            timestamp_ms=1710000000000,
            source_device="1",
            source="signal",
            group_id="group-1",
            quote_target_timestamp_ms=1710000000001,
            reaction_target_timestamp_ms=1710000000002,
            reaction_emoji="👍",
            approval_intent="approve",
            reply_to_proposal_token="reply-1",
            reaction_to_proposal_token="react-1",
        ),
    )
    outbound = repo.insert_turn(
        session_id=session.id,
        direction=TurnDirection.OUTBOUND,
        content="world",
        role="assistant",
        model="gpt-oss",
        provider="ollama",
        token_count=3,
        reasoning_level="standard",
        trace_id="trace-2",
        conversation_episode_id="episode-2",
        principal="operator",
        delivery=OutboundDeliveryRecord(state="candidate"),
    )

    updated = repo.update_turn_delivery(
        turn_id=outbound.id,
        delivery=OutboundDeliveryRecord(
            state="delivered",
            delivered_at_ms=1710000001000,
            detail="sent",
        ),
    )

    assert inbound.sender_e164 == "+12025550100"
    assert inbound.source == "signal"
    assert inbound.reply_to_proposal_token == "reply-1"
    assert updated is not None
    assert updated.delivery_state == "delivered"
    assert updated.delivery_timestamp_ms == 1710000001000
    assert updated.delivery_detail == "sent"


def test_get_latest_session_returns_newest_session(
    migrated_integration_settings,
) -> None:
    """Repository should return the most recently created session when no updates occur."""
    runtime = MemoryPostgresRuntime.from_settings(migrated_integration_settings)
    repo = PostgresMemoryRepository(runtime.schema_sessions)

    first = repo.create_session()
    second = repo.create_session()

    latest = repo.get_latest_session()

    assert latest is not None
    assert latest.id == second.id
    assert latest.id != first.id
