"""Unit tests for Policy Service authorization behaviors."""

from __future__ import annotations

from packages.brain_shared.envelope import EnvelopeKind, new_meta
from services.action.policy_service.config import PolicyServiceSettings
from services.action.policy_service.domain import (
    CapabilityInvocationRequest,
    CapabilityRef,
    PolicyContext,
    PolicyDecision,
    PolicyExecutionResult,
    utc_now,
)
from services.action.policy_service.implementation import DefaultPolicyService


def _decision() -> PolicyDecision:
    return PolicyDecision(
        decision_id="tmp",
        allowed=True,
        reason_codes=(),
        obligations=(),
        policy_metadata={},
        decided_at=utc_now(),
        policy_name="tmp",
        policy_version="1",
    )


def _request(
    *, envelope_id: str = "env-1", approval_token: str = ""
) -> CapabilityInvocationRequest:
    return CapabilityInvocationRequest(
        metadata=new_meta(
            kind=EnvelopeKind.COMMAND,
            source="test",
            principal="operator",
            envelope_id=envelope_id,
            trace_id="trace-1",
        ),
        capability=CapabilityRef(
            kind="op",
            namespace="core",
            name="ping",
            version="v1",
        ),
        input_payload={"ping": "pong"},
        policy_context=PolicyContext(
            actor="operator",
            channel="signal",
            invocation_id="inv-1",
            approval_token=approval_token,
        ),
        declared_autonomy=0,
        requires_approval=False,
    )


def test_dedupe_denies_duplicate_envelope_within_window() -> None:
    service = DefaultPolicyService(
        settings=PolicyServiceSettings(dedupe_window_seconds=60)
    )
    req = _request(envelope_id="dedupe-1")

    first = service.authorize_and_execute(
        request=req,
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )
    second = service.authorize_and_execute(
        request=req,
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )

    assert first.allowed is True
    assert second.allowed is False
    assert "dedupe_duplicate_request" in second.decision.reason_codes


def test_approval_required_emits_proposal_and_denies() -> None:
    service = DefaultPolicyService(settings=PolicyServiceSettings())
    req = _request()
    req = req.model_copy(update={"requires_approval": True})

    result = service.authorize_and_execute(
        request=req,
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )

    assert result.allowed is False
    assert result.proposal is not None
    assert "approval_required" in result.decision.reason_codes


def test_valid_approval_token_allows_execution() -> None:
    service = DefaultPolicyService(settings=PolicyServiceSettings())
    base = _request()
    pending = service.authorize_and_execute(
        request=base.model_copy(update={"requires_approval": True}),
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )
    assert pending.proposal is not None

    token = pending.proposal.proposal_id
    approved_request = base.model_copy(
        update={
            "requires_approval": True,
            "policy_context": base.policy_context.model_copy(
                update={"approval_token": token, "invocation_id": "inv-2"}
            ),
            "metadata": base.metadata.model_copy(update={"envelope_id": "env-2"}),
        }
    )

    approved = service.authorize_and_execute(
        request=approved_request,
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )

    assert approved.allowed is True
    assert approved.output == {"ok": True}
