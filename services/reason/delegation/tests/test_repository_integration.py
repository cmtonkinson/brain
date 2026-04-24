"""Real-Postgres integration tests for the Delegation repository.

These exercise the SQL surface against an ephemeral Postgres container set
up by ``tests/integration/fixtures.py``. They are skipped unless the
``BRAIN_RUN_INTEGRATION_REAL`` env var is set, mirroring the convention
used by sibling services (Recall, Language).

The shared Postgres fixture is session-scoped and not cleaned up between
tests, so each test below explicitly truncates ``delegation.invocation``
to give itself an isolated starting point. This keeps assertions about
"the oldest queued row" honest under arbitrary execution order.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from services.reason.delegation.data.repository import DelegationRepository
from services.reason.delegation.data.runtime import (
    DelegationPostgresRuntime,
    delegation_postgres_schema,
)
from services.reason.delegation.domain import (
    CancelReason,
    InvocationRequest,
    InvocationStatus,
)
from tests.integration.helpers import real_provider_tests_enabled

pytest_plugins = ("tests.integration.fixtures",)


pytestmark = pytest.mark.skipif(
    not real_provider_tests_enabled(),
    reason="set BRAIN_RUN_INTEGRATION_REAL=1 to run real-provider integration tests",
)


def _repository(settings) -> DelegationRepository:
    """Build the Postgres repository against an integration-test settings object."""
    runtime = DelegationPostgresRuntime.from_settings(settings)
    _truncate_invocations(runtime)
    return DelegationRepository(runtime.schema_sessions)


def _truncate_invocations(runtime: DelegationPostgresRuntime) -> None:
    """Wipe the invocation table so tests start from a known empty state."""
    schema = delegation_postgres_schema()
    with runtime.engine.begin() as connection:
        connection.execute(sa.text(f"TRUNCATE TABLE {schema}.invocation"))


def _request(prompt: str = "task") -> InvocationRequest:
    """Return one minimal invocation request used across these tests."""
    return InvocationRequest(prompt=prompt)


def test_insert_and_read_status_roundtrip(migrated_integration_settings) -> None:
    """Inserted invocations round-trip through the repository read API."""
    repo = _repository(migrated_integration_settings)

    invocation_id = repo.insert_invocation(
        request=_request("hello"),
        principal="operator",
        channel="agent",
        depth=0,
    )

    status = repo.read_status(invocation_id=invocation_id)
    assert status is not None
    assert status.invocation_id == invocation_id
    assert status.status == InvocationStatus.queued
    assert status.tokens_in == 0
    assert status.tokens_out == 0
    assert status.turn_count == 0


def test_claim_skips_locked_and_transitions_to_running(
    migrated_integration_settings,
) -> None:
    """Atomic claim transitions the oldest queued row to running."""
    repo = _repository(migrated_integration_settings)

    repo.insert_invocation(
        request=_request("first"),
        principal="operator",
        channel="agent",
        depth=0,
    )
    repo.insert_invocation(
        request=_request("second"),
        principal="operator",
        channel="agent",
        depth=0,
    )

    claim = repo.claim_next_queued(
        now=datetime.now(UTC),
        claimed_by="subagent",
    )
    assert claim is not None
    assert claim.prompt == "first"
    status = repo.read_status(invocation_id=claim.invocation_id)
    assert status is not None
    assert status.status == InvocationStatus.running


def test_bump_turn_with_totals_sets_authoritative_columns(
    migrated_integration_settings,
) -> None:
    """``bump_turn_with_totals`` overwrites token columns with audit totals."""
    repo = _repository(migrated_integration_settings)
    invocation_id = repo.insert_invocation(
        request=_request("token-test"),
        principal="operator",
        channel="agent",
        depth=0,
    )

    view = repo.bump_turn_with_totals(
        invocation_id=invocation_id, tokens_in=42, tokens_out=84
    )
    assert view is not None
    assert view.tokens_in == 42
    assert view.tokens_out == 84
    assert view.turn_count == 1

    # A subsequent bump replaces totals (not deltas).
    view = repo.bump_turn_with_totals(
        invocation_id=invocation_id, tokens_in=100, tokens_out=200
    )
    assert view is not None
    assert view.tokens_in == 100
    assert view.tokens_out == 200
    assert view.turn_count == 2


def test_finalize_terminal_only(migrated_integration_settings) -> None:
    """Finalize sets the row to a terminal state and persists final_response."""
    repo = _repository(migrated_integration_settings)
    invocation_id = repo.insert_invocation(
        request=_request("finalize"),
        principal="operator",
        channel="agent",
        depth=0,
    )

    result = repo.finalize(
        invocation_id=invocation_id,
        status=InvocationStatus.succeeded,
        final_response="42",
    )
    assert result is not None
    assert result.status == InvocationStatus.succeeded
    assert result.final_response == "42"


def test_mark_canceling_then_finalize_canceled(
    migrated_integration_settings,
) -> None:
    """Cancellation flows: queued/running -> canceling -> canceled with reason."""
    repo = _repository(migrated_integration_settings)
    invocation_id = repo.insert_invocation(
        request=_request("cancel-flow"),
        principal="operator",
        channel="agent",
        depth=0,
    )

    assert repo.mark_canceling(invocation_id=invocation_id, reason=CancelReason.manual)
    status = repo.read_status(invocation_id=invocation_id)
    assert status is not None
    assert status.status == InvocationStatus.canceling
    assert status.cancel_reason == CancelReason.manual

    final = repo.finalize(
        invocation_id=invocation_id,
        status=InvocationStatus.canceled,
        final_response=None,
        cancel_reason=CancelReason.manual,
    )
    assert final is not None
    assert final.status == InvocationStatus.canceled
    assert final.cancel_reason == CancelReason.manual


def test_sweep_wallclock_marks_stale_running(migrated_integration_settings) -> None:
    """Sweeper flips running invocations whose deadline has passed."""
    repo = _repository(migrated_integration_settings)
    invocation_id = repo.insert_invocation(
        request=InvocationRequest(prompt="long-run", max_wallclock_seconds=1),
        principal="operator",
        channel="agent",
        depth=0,
    )
    # Claim transitions to running and stamps started_at; pretend the row
    # was claimed long enough ago that the deadline has elapsed by sweeping
    # with ``now`` set well into the future.
    claim = repo.claim_next_queued(now=datetime.now(UTC), claimed_by="subagent")
    assert claim is not None
    assert claim.invocation_id == invocation_id

    affected = repo.sweep_wallclock(now=datetime.now(UTC) + timedelta(seconds=10))
    assert invocation_id in affected
    status = repo.read_status(invocation_id=invocation_id)
    assert status is not None
    assert status.status == InvocationStatus.canceling
    assert status.cancel_reason == CancelReason.budget_wallclock


def test_list_children_for_cascade_cancel(migrated_integration_settings) -> None:
    """Parent->child relationships round-trip via ``list_children``."""
    repo = _repository(migrated_integration_settings)
    parent_id = repo.insert_invocation(
        request=_request("parent"),
        principal="operator",
        channel="agent",
        depth=0,
    )
    child_id = repo.insert_invocation(
        request=InvocationRequest(prompt="child", parent_invocation_id=parent_id),
        principal="operator",
        channel="agent",
        depth=1,
    )

    children = repo.list_children(parent_invocation_id=parent_id)
    assert children == [child_id]


def test_read_depth_returns_persisted_depth(migrated_integration_settings) -> None:
    """``read_depth`` returns the depth column for one row."""
    repo = _repository(migrated_integration_settings)
    invocation_id = repo.insert_invocation(
        request=_request("depth"),
        principal="operator",
        channel="agent",
        depth=3,
    )

    assert repo.read_depth(invocation_id=invocation_id) == 3
    assert repo.read_depth(invocation_id="01H00000000000000000000000") is None
