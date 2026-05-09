"""Tests for the Brain Subagent Actor's pure execution units.

The poll loop and signal handlers are intentionally not exercised here; only
the per-invocation dispatch logic and small utility helpers are tested.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import pytest

from lib.agent import CancellationError, CancelReason, LoopResult, TurnSummary
from lib.sdk.calls import (
    DelegationCancelOutcome,
    DelegationClaim,
    DelegationResult,
    DelegationStatusView,
    DelegationTurnDecision,
    OpInvokeResult,
    PolicyDecision,
)
from lib.agent.subagent_runtime import (
    build_cancel_check,
    build_record_turn,
    coerce_object_text,
    run_invocation,
    safe_finalize,
)
from lib.sdk.client import BrainClient
from actors.subagent.main import (
    _resolve_heartbeat_path,
    _write_heartbeat,
)


def _make_claim(
    *,
    invocation_id: str = "01H000000000000000000INVOC",
    parent_invocation_id: str | None = None,
    prompt: str = "do the thing",
    context_text: str | None = None,
    context_object_refs: tuple[str, ...] = (),
    tool_allowlist: tuple[str, ...] | None = None,
    max_turns: int = 4,
) -> DelegationClaim:
    return DelegationClaim(
        invocation_id=invocation_id,
        parent_invocation_id=parent_invocation_id,
        principal="subagent",
        channel="subagent",
        personality_id="subagent",
        prompt=prompt,
        context_text=context_text,
        context_object_refs=context_object_refs,
        tool_allowlist=tool_allowlist,
        max_turns=max_turns,
        budget_tokens=None,
        max_wallclock_seconds=None,
    )


@dataclass
class _Recorded:
    method: str
    kwargs: dict[str, Any]


@dataclass
class _FakeClientState:
    finalize_calls: list[_Recorded] = field(default_factory=list)
    invoke_calls: list[_Recorded] = field(default_factory=list)
    status_response: DelegationStatusView | None = None
    record_response: DelegationTurnDecision | None = None
    object_text: dict[str, str] = field(default_factory=dict)


class _FakeClient:
    """In-memory BrainClient stand-in for subagent unit tests."""

    def __init__(self, *, run_loop: Any = None) -> None:
        self.state = _FakeClientState()
        self._run_loop = run_loop

    # delegation surface ---------------------------------------------------

    def delegation_finalize_invocation(self, **kwargs: Any) -> DelegationResult:
        self.state.finalize_calls.append(_Recorded("finalize", kwargs))
        return DelegationResult(
            invocation_id=str(kwargs.get("invocation_id", "")),
            status=str(kwargs.get("status", "")),
            final_response=kwargs.get("final_response"),
            cancel_reason=kwargs.get("cancel_reason"),
            tokens_in=0,
            tokens_out=0,
            turn_count=0,
        )

    def delegation_status(self, *, invocation_id: str) -> DelegationStatusView:
        if self.state.status_response is not None:
            return self.state.status_response
        return DelegationStatusView(
            invocation_id=invocation_id,
            status="running",
            cancel_reason=None,
            tokens_in=0,
            tokens_out=0,
            turn_count=0,
            started_at=None,
            completed_at=None,
        )

    def delegation_record_turn(
        self,
        *,
        invocation_id: str,  # noqa: ARG002
    ) -> DelegationTurnDecision:
        if self.state.record_response is not None:
            return self.state.record_response
        return DelegationTurnDecision(should_stop=False, reason=None)

    def delegation_cancel(
        self,
        *,
        invocation_id: str,  # noqa: ARG002
        reason: str = "manual",  # noqa: ARG002
    ) -> DelegationCancelOutcome:
        return DelegationCancelOutcome(accepted=True)

    # ops surface ----------------------------------------------------------

    def invoke_op(self, **kwargs: Any) -> OpInvokeResult:
        self.state.invoke_calls.append(_Recorded("invoke_op", kwargs))
        op_id = str(kwargs.get("op_id", ""))
        if op_id == "object-get-text":
            payload = kwargs.get("input_payload") or {}
            ref = str(payload.get("key", ""))
            text = self.state.object_text.get(ref, "")
            return OpInvokeResult(
                output={"text": text},
                policy=PolicyDecision(
                    decision_id="d",
                    allowed=True,
                    reason_codes=(),
                    obligations=(),
                    proposal_id="",
                ),
            )
        return OpInvokeResult(
            output=None,
            policy=PolicyDecision(
                decision_id="d",
                allowed=True,
                reason_codes=(),
                obligations=(),
                proposal_id="",
            ),
        )


def _as_client(client: _FakeClient) -> BrainClient:
    return cast(BrainClient, client)


def test_coerce_object_text_handles_common_shapes() -> None:
    assert coerce_object_text("plain") == "plain"
    assert coerce_object_text({"text": "wrapped"}) == "wrapped"
    assert coerce_object_text({"content": "alt"}) == "alt"
    assert coerce_object_text(None) == ""
    assert coerce_object_text(42) == ""


def test_cancel_check_returns_continue_when_running() -> None:
    client = _FakeClient()
    check = build_cancel_check(client=_as_client(client), invocation_id="abc")
    decision = check()
    assert decision.should_stop is False
    assert decision.reason is None


def test_cancel_check_returns_stop_when_canceling() -> None:
    client = _FakeClient()
    client.state.status_response = DelegationStatusView(
        invocation_id="abc",
        status="canceling",
        cancel_reason="manual",
        tokens_in=0,
        tokens_out=0,
        turn_count=0,
        started_at=None,
        completed_at=None,
    )
    decision = build_cancel_check(client=_as_client(client), invocation_id="abc")()
    assert decision.should_stop is True
    assert decision.reason == CancelReason.manual


def test_record_turn_propagates_stop_reason() -> None:
    client = _FakeClient()
    client.state.record_response = DelegationTurnDecision(
        should_stop=True, reason="budget_tokens"
    )
    decision = build_record_turn(client=_as_client(client), invocation_id="abc")(
        TurnSummary(turn_index=0)
    )
    assert decision.should_stop is True
    assert decision.reason == CancelReason.budget_tokens


def test_run_invocation_succeeds_and_finalizes(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def _fake_run(**kwargs: Any) -> LoopResult:
        captured.update(kwargs)
        return LoopResult(
            final_response="42",
            turn_count=1,
            exhausted=False,
        )

    monkeypatch.setattr("lib.agent.subagent_runtime.run_agent_loop", _fake_run)
    client = _FakeClient()
    claim = _make_claim()

    run_invocation(client=_as_client(client), claim=claim)

    assert len(client.state.finalize_calls) == 1
    finalize_kwargs = client.state.finalize_calls[0].kwargs
    assert finalize_kwargs["invocation_id"] == claim.invocation_id
    assert finalize_kwargs["status"] == "succeeded"
    assert finalize_kwargs["final_response"] == "42"
    assert captured["principal"] == "subagent"
    assert captured["source"] == "subagent"
    assert captured["channel"] == "subagent"
    assert captured["max_turns"] == claim.max_turns


def test_run_invocation_handles_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_run(**_: Any) -> LoopResult:
        raise CancellationError(CancelReason.manual)

    monkeypatch.setattr("lib.agent.subagent_runtime.run_agent_loop", _fake_run)
    client = _FakeClient()
    claim = _make_claim()

    run_invocation(client=_as_client(client), claim=claim)

    finalize_kwargs = client.state.finalize_calls[0].kwargs
    assert finalize_kwargs["status"] == "canceled"
    assert finalize_kwargs["cancel_reason"] == "manual"


def test_run_invocation_resolves_object_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def _fake_run(**kwargs: Any) -> LoopResult:
        captured.update(kwargs)
        return LoopResult(
            final_response="ok",
            turn_count=1,
            exhausted=False,
        )

    monkeypatch.setattr("lib.agent.subagent_runtime.run_agent_loop", _fake_run)
    client = _FakeClient()
    client.state.object_text = {"obj-1": "ref-text-one", "obj-2": "ref-text-two"}
    claim = _make_claim(
        prompt="task",
        context_text="inline ctx",
        context_object_refs=("obj-1", "obj-2"),
    )

    run_invocation(client=_as_client(client), claim=claim)

    object_calls = [
        c for c in client.state.invoke_calls if c.kwargs["op_id"] == "object-get-text"
    ]
    assert len(object_calls) == 2
    # Prompt stays clean; context flows through the loop's structured channel.
    assert captured["prompt"] == "task"
    context_text = captured.get("context_text") or ""
    assert "inline ctx" in context_text
    assert "ref-text-one" in context_text
    assert "ref-text-two" in context_text


def test_safe_finalize_swallows_secondary_errors() -> None:
    class _ExplodingClient:
        def delegation_finalize_invocation(self, **_: Any) -> None:
            raise RuntimeError("boom")

    safe_finalize(
        client=_ExplodingClient(),  # type: ignore[arg-type]
        invocation_id="abc",
        status="failed",
        final_response="bang",
    )


def test_resolve_heartbeat_path_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRAIN_SUBAGENT_HEARTBEAT_FILE", raising=False)
    assert _resolve_heartbeat_path() == Path("/run/brain/subassistant-heartbeat")


def test_resolve_heartbeat_path_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAIN_SUBAGENT_HEARTBEAT_FILE", "/tmp/sa-heartbeat")
    assert _resolve_heartbeat_path() == Path("/tmp/sa-heartbeat")


def test_write_heartbeat_creates_nested(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "heartbeat"
    _write_heartbeat(target)
    assert target.exists()
