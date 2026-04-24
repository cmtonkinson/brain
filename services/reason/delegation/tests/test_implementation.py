"""Unit tests for DefaultDelegationService against a stub repository."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any

import pytest

from lib.shared.envelope import EnvelopeKind, new_meta
from lib.shared.ids import generate_ulid_str
from services.reason.delegation.domain import (
    CancelReason,
    ClaimedInvocation,
    InvocationRequest,
    InvocationResult,
    InvocationStatus,
    InvocationStatusView,
)
from services.reason.delegation.implementation import DefaultDelegationService


class _FakeRepository:
    """Stub repository persisting invocations in-memory for unit tests."""

    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}

    def insert_invocation(
        self,
        *,
        request: InvocationRequest,
        principal: str,
        channel: str,
        depth: int,
    ) -> str:
        invocation_id = generate_ulid_str()
        now = datetime.now(UTC)
        self._rows[invocation_id] = {
            "id": invocation_id,
            "parent_invocation_id": request.parent_invocation_id,
            "depth": depth,
            "status": InvocationStatus.queued.value,
            "cancel_reason": None,
            "principal": principal,
            "channel": channel,
            "personality_id": request.personality_id,
            "prompt": request.prompt,
            "context_text": request.context_text,
            "context_object_refs": list(request.context_object_refs),
            "tool_allowlist": (
                None if request.tool_allowlist is None else list(request.tool_allowlist)
            ),
            "max_turns": request.max_turns,
            "budget_tokens": request.budget_tokens,
            "max_wallclock_seconds": request.max_wallclock_seconds,
            "tokens_in": 0,
            "tokens_out": 0,
            "turn_count": 0,
            "final_response": None,
            "transcript_ref": None,
            "claimed_by": None,
            "claimed_at": None,
            "started_at": None,
            "completed_at": None,
            "created_at": now,
            "updated_at": now,
        }
        return invocation_id

    def read_status(self, *, invocation_id: str) -> InvocationStatusView | None:
        row = self._rows.get(invocation_id)
        if row is None:
            return None
        return InvocationStatusView(
            invocation_id=invocation_id,
            status=InvocationStatus(row["status"]),
            cancel_reason=(
                None
                if row["cancel_reason"] is None
                else CancelReason(row["cancel_reason"])
            ),
            tokens_in=row["tokens_in"],
            tokens_out=row["tokens_out"],
            turn_count=row["turn_count"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
        )

    def read_result(self, *, invocation_id: str) -> InvocationResult | None:
        row = self._rows.get(invocation_id)
        if row is None:
            return None
        return InvocationResult(
            invocation_id=invocation_id,
            status=InvocationStatus(row["status"]),
            final_response=row["final_response"],
            cancel_reason=(
                None
                if row["cancel_reason"] is None
                else CancelReason(row["cancel_reason"])
            ),
            tokens_in=row["tokens_in"],
            tokens_out=row["tokens_out"],
            turn_count=row["turn_count"],
        )

    def list_children(self, *, parent_invocation_id: str) -> list[str]:
        return [
            row_id
            for row_id, row in self._rows.items()
            if row["parent_invocation_id"] == parent_invocation_id
        ]

    def claim_next_queued(
        self, *, now: datetime, claimed_by: str
    ) -> ClaimedInvocation | None:
        candidates = sorted(
            (
                row
                for row in self._rows.values()
                if row["status"] == InvocationStatus.queued.value
            ),
            key=lambda row: row["created_at"],
        )
        if not candidates:
            return None
        row = candidates[0]
        row["status"] = InvocationStatus.running.value
        row["claimed_by"] = claimed_by
        row["claimed_at"] = now
        row["started_at"] = now
        row["updated_at"] = now
        return ClaimedInvocation(
            invocation_id=row["id"],
            parent_invocation_id=row["parent_invocation_id"],
            principal=row["principal"],
            channel=row["channel"],
            personality_id=row["personality_id"],
            prompt=row["prompt"],
            context_text=row["context_text"],
            context_object_refs=tuple(row["context_object_refs"]),
            tool_allowlist=(
                None if row["tool_allowlist"] is None else tuple(row["tool_allowlist"])
            ),
            max_turns=row["max_turns"],
            budget_tokens=row["budget_tokens"],
            max_wallclock_seconds=row["max_wallclock_seconds"],
        )

    def bump_turn_with_totals(
        self,
        *,
        invocation_id: str,
        tokens_in: int,
        tokens_out: int,
    ) -> InvocationStatusView | None:
        row = self._rows.get(invocation_id)
        if row is None:
            return None
        row["tokens_in"] = tokens_in
        row["tokens_out"] = tokens_out
        row["turn_count"] += 1
        row["updated_at"] = datetime.now(UTC)
        return self.read_status(invocation_id=invocation_id)

    def mark_canceling(self, *, invocation_id: str, reason: CancelReason) -> bool:
        row = self._rows.get(invocation_id)
        if row is None:
            return False
        if row["status"] not in (
            InvocationStatus.queued.value,
            InvocationStatus.running.value,
        ):
            return False
        row["status"] = InvocationStatus.canceling.value
        row["cancel_reason"] = reason.value
        row["updated_at"] = datetime.now(UTC)
        return True

    def finalize(
        self,
        *,
        invocation_id: str,
        status: InvocationStatus,
        final_response: str | None,
        transcript_ref: str | None = None,
        cancel_reason: CancelReason | None = None,
    ) -> InvocationResult | None:
        row = self._rows.get(invocation_id)
        if row is None:
            return None
        row["status"] = status.value
        row["final_response"] = final_response
        row["transcript_ref"] = transcript_ref
        if cancel_reason is not None:
            row["cancel_reason"] = cancel_reason.value
        row["completed_at"] = datetime.now(UTC)
        row["updated_at"] = row["completed_at"]
        return self.read_result(invocation_id=invocation_id)

    def read_ceilings(self, *, invocation_id: str) -> tuple[int, int | None] | None:
        row = self._rows.get(invocation_id)
        if row is None:
            return None
        return (row["max_turns"], row["budget_tokens"])

    def read_depth(self, *, invocation_id: str) -> int | None:
        row = self._rows.get(invocation_id)
        if row is None:
            return None
        return int(row["depth"])

    def sweep_wallclock(self, *, now: datetime) -> list[str]:
        affected: list[str] = []
        for row in self._rows.values():
            if row["status"] != InvocationStatus.running.value:
                continue
            started_at = row["started_at"]
            max_seconds = row["max_wallclock_seconds"]
            if started_at is None or max_seconds is None:
                continue
            if (now - started_at).total_seconds() >= max_seconds:
                row["status"] = InvocationStatus.canceling.value
                row["cancel_reason"] = CancelReason.budget_wallclock.value
                affected.append(row["id"])
        return affected


class _StubLanguageModel:
    """Configurable Language stand-in returning canned token totals.

    Tests inject a pre-set ``totals`` map keyed by ``trace_id`` (i.e.
    invocation id). Defaults to zero so budget breaches must be reproduced
    by explicitly configuring the totals.
    """

    def __init__(self) -> None:
        self.totals: dict[str, tuple[int, int]] = {}

    def get_token_usage_by_trace(self, *, meta: Any, trace_id: str) -> Any:  # noqa: ARG002
        from services.effect.language.domain import TokenUsageTotals

        input_tokens, output_tokens = self.totals.get(trace_id, (0, 0))
        from lib.shared.envelope import success as _success

        return _success(
            meta=meta,
            payload=TokenUsageTotals(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
                call_count=1 if (input_tokens or output_tokens) else 0,
            ),
        )


@pytest.fixture
def language_stub() -> _StubLanguageModel:
    """Return a fresh language stub for direct test manipulation."""
    return _StubLanguageModel()


@pytest.fixture
def service(language_stub: _StubLanguageModel) -> DefaultDelegationService:
    """Build a service with the stub repository, stub Language, no sweeper."""
    instance = DefaultDelegationService.__new__(DefaultDelegationService)
    instance._repository = _FakeRepository()  # type: ignore[attr-defined]
    instance._language_model = language_stub  # type: ignore[attr-defined]
    instance._max_recursion_depth = 4
    instance._sweeper_interval = 60.0
    instance._waiters_lock = threading.Lock()
    instance._waiters = {}
    instance._stop_event = threading.Event()
    instance._sweeper_thread = None
    return instance


def _meta() -> Any:
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def test_invoke_then_get_status_then_finalize(
    service: DefaultDelegationService,
) -> None:
    started = service.invoke(meta=_meta(), prompt="add 2 and 2")
    assert started.payload is not None
    invocation_id = started.payload.value.invocation_id

    status = service.get_status(meta=_meta(), invocation_id=invocation_id)
    assert status.payload is not None
    assert status.payload.value.status == InvocationStatus.queued

    final = service.finalize_invocation(
        meta=_meta(),
        invocation_id=invocation_id,
        status=InvocationStatus.succeeded,
        final_response="4",
    )
    assert final.payload is not None
    assert final.payload.value.status == InvocationStatus.succeeded
    assert final.payload.value.final_response == "4"


def test_invoke_and_wait_unblocks_on_finalize(
    service: DefaultDelegationService,
) -> None:
    completed_id: dict[str, str] = {}

    def _finalize_in_background() -> None:
        # Spin until the invocation row exists, then finalize.
        for _ in range(200):
            for invocation_id, _row in service._repository._rows.items():  # noqa: SLF001
                completed_id["id"] = invocation_id
                service.finalize_invocation(
                    meta=_meta(),
                    invocation_id=invocation_id,
                    status=InvocationStatus.succeeded,
                    final_response="ok",
                )
                return
            threading.Event().wait(timeout=0.01)

    finalizer = threading.Thread(target=_finalize_in_background, daemon=True)
    finalizer.start()
    result = service.invoke_and_wait(
        meta=_meta(), prompt="finalize me", timeout_seconds=2.0
    )
    finalizer.join(timeout=2.0)
    assert result.payload is not None
    assert result.payload.value.status == InvocationStatus.succeeded
    assert result.payload.value.final_response == "ok"
    assert completed_id["id"] != ""


def test_cancel_marks_canceling(service: DefaultDelegationService) -> None:
    started = service.invoke(meta=_meta(), prompt="be canceled")
    assert started.payload is not None
    invocation_id = started.payload.value.invocation_id

    outcome = service.cancel(meta=_meta(), invocation_id=invocation_id)
    assert outcome.payload is not None
    assert outcome.payload.value.accepted is True

    status = service.get_status(meta=_meta(), invocation_id=invocation_id)
    assert status.payload is not None
    assert status.payload.value.status == InvocationStatus.canceling
    assert status.payload.value.cancel_reason == CancelReason.manual


def test_record_turn_budget_breach(
    service: DefaultDelegationService, language_stub: _StubLanguageModel
) -> None:
    started = service.invoke(
        meta=_meta(),
        prompt="run",
        max_turns=8,
        budget_tokens=100,
    )
    assert started.payload is not None
    invocation_id = started.payload.value.invocation_id
    # Audit reports 60 input + 60 output; combined exceeds the 100 budget.
    language_stub.totals[invocation_id] = (60, 60)

    decision = service.record_turn(
        meta=_meta(),
        invocation_id=invocation_id,
    )
    assert decision.payload is not None
    assert decision.payload.value.should_stop is True
    assert decision.payload.value.reason == CancelReason.budget_tokens


def test_record_turn_budget_turns_breach(
    service: DefaultDelegationService,
) -> None:
    started = service.invoke(meta=_meta(), prompt="run", max_turns=2)
    assert started.payload is not None
    invocation_id = started.payload.value.invocation_id

    service.record_turn(meta=_meta(), invocation_id=invocation_id)
    decision = service.record_turn(meta=_meta(), invocation_id=invocation_id)
    assert decision.payload is not None
    assert decision.payload.value.should_stop is True
    assert decision.payload.value.reason == CancelReason.budget_turns


def test_claim_returns_oldest_queued(service: DefaultDelegationService) -> None:
    first = service.invoke(meta=_meta(), prompt="first")
    service.invoke(meta=_meta(), prompt="second")
    assert first.payload is not None
    expected_id = first.payload.value.invocation_id

    claim = service.claim_next_invocation(meta=_meta(), claimed_by="subagent")
    assert claim.payload is not None
    assert claim.payload.value is not None
    assert claim.payload.value.invocation_id == expected_id
    assert claim.payload.value.prompt == "first"


def test_sweep_wallclock_marks_stale_running_invocations(
    service: DefaultDelegationService,
) -> None:
    """Wallclock sweeper flips running invocations past their deadline."""
    started = service.invoke(
        meta=_meta(),
        prompt="long-running",
        max_wallclock_seconds=1,
    )
    assert started.payload is not None
    invocation_id = started.payload.value.invocation_id
    # Manually transition the row to running with a stale started_at so the
    # sweeper sees a deadline in the past without waiting on the daemon
    # thread (the unit fixture intentionally skips the sweeper start).
    repo = service._repository  # noqa: SLF001
    row = repo._rows[invocation_id]  # noqa: SLF001
    row["status"] = InvocationStatus.running.value
    row["started_at"] = datetime.now(UTC).replace(year=2000)

    affected = repo.sweep_wallclock(now=datetime.now(UTC))

    assert invocation_id in affected
    status = service.get_status(meta=_meta(), invocation_id=invocation_id)
    assert status.payload is not None
    assert status.payload.value.status == InvocationStatus.canceling
    assert status.payload.value.cancel_reason == CancelReason.budget_wallclock


def test_invoke_rejects_when_recursion_depth_exceeded(
    service: DefaultDelegationService,
) -> None:
    """Each child increments depth by 1; service rejects beyond ceiling."""
    # Service fixture uses max_recursion_depth=4 (admits depths 0..4).
    # Build a 4-deep chain (depths 0..4), then a 5th-depth child should fail.
    parent_id: str | None = None
    for _ in range(5):
        envelope = service.invoke(
            meta=_meta(),
            prompt="link",
            parent_invocation_id=parent_id,
        )
        assert envelope.payload is not None, envelope.errors
        parent_id = envelope.payload.value.invocation_id

    rejected = service.invoke(
        meta=_meta(),
        prompt="too deep",
        parent_invocation_id=parent_id,
    )
    assert rejected.payload is None
    assert rejected.errors
    assert any(
        "recursion depth" in str(getattr(error, "message", "")).lower()
        for error in rejected.errors
    )


def test_cancel_cascades_to_children(service: DefaultDelegationService) -> None:
    parent = service.invoke(meta=_meta(), prompt="parent")
    assert parent.payload is not None
    parent_id = parent.payload.value.invocation_id

    child = service.invoke(meta=_meta(), prompt="child", parent_invocation_id=parent_id)
    assert child.payload is not None
    child_id = child.payload.value.invocation_id

    service.cancel(meta=_meta(), invocation_id=parent_id)
    child_status = service.get_status(meta=_meta(), invocation_id=child_id)
    assert child_status.payload is not None
    assert child_status.payload.value.status == InvocationStatus.canceling
    assert child_status.payload.value.cancel_reason == CancelReason.parent_canceled
