"""Unit tests for scheduled actor context helpers."""

from __future__ import annotations

from scheduler.actor_context import (
    SCHEDULED_ACTOR_TYPE,
    SCHEDULED_AUTONOMY_LEVEL,
    SCHEDULED_CHANNEL,
    SCHEDULED_PRIVILEGE_LEVEL,
    ScheduledActorContext,
)


def test_scheduled_actor_context_reference_includes_min_fields() -> None:
    """Ensure scheduled actor context reference includes required fields."""
    context = ScheduledActorContext()
    reference = context.to_reference(trigger_source="run_now", requested_by="human@signal")

    assert f"actor_type={SCHEDULED_ACTOR_TYPE}" in reference
    assert f"channel={SCHEDULED_CHANNEL}" in reference
    assert f"autonomy={SCHEDULED_AUTONOMY_LEVEL}" in reference
    assert f"privilege={SCHEDULED_PRIVILEGE_LEVEL}" in reference
    assert "trigger=run_now" in reference
    assert "requested_by=human@signal" in reference
