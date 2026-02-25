"""Unit tests for Policy Service authorization behaviors."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.brain_shared.envelope import EnvelopeKind, failure, new_meta, success
from packages.brain_shared.errors import dependency_error
from services.action.attention_router.domain import (
    ApprovalCorrelationPayload as RouterApprovalCorrelationPayload,
    ApprovalNotificationPayload as RouterApprovalNotificationPayload,
    HealthStatus as AttentionRouterHealthStatus,
    RouteNotificationResult,
)
from services.action.attention_router.service import AttentionRouterService
from services.action.policy_service.config import PolicyServiceSettings
from services.action.policy_service.data.repository import (
    InMemoryPolicyPersistenceRepository,
)
from services.action.policy_service.domain import (
    ApprovalCorrelationPayload,
    ApprovalNotificationPayload,
    CapabilityInvocationRequest,
    CapabilityPolicyInput,
    InvocationPolicyInput,
    PolicyDecision,
    PolicyDocument,
    PolicyExecutionResult,
    PolicyOverlay,
    PolicyRule,
    PolicyRuleOverlay,
    utc_now,
)
from services.action.policy_service.implementation import DefaultPolicyService


def _decision() -> PolicyDecision:
    return PolicyDecision(
        decision_id="tmp",
        policy_regime_id="regime-1",
        policy_regime_hash="hash-1",
        allowed=True,
        reason_codes=(),
        obligations=(),
        policy_metadata={},
        decided_at=utc_now(),
        policy_name="tmp",
        policy_version="1",
    )


class _FakeAttentionRouterService(AttentionRouterService):
    """Test double for Policy Service approval-notification routing calls."""

    def __init__(self) -> None:
        self.approval_payloads: list[RouterApprovalNotificationPayload] = []
        self.fail_approval_routing: bool = False

    def route_notification(self, *, meta, **kwargs):
        del meta, kwargs
        return success(
            meta=new_meta(kind=EnvelopeKind.EVENT, source="test", principal="operator"),
            payload=RouteNotificationResult(
                decision="sent",
                delivered=True,
                detail="ok",
            ),
        )

    def route_approval_notification(self, *, meta, approval):
        del meta
        self.approval_payloads.append(approval)
        if self.fail_approval_routing:
            return failure(
                meta=new_meta(
                    kind=EnvelopeKind.EVENT, source="test", principal="operator"
                ),
                errors=[dependency_error("signal unavailable")],
            )
        return success(
            meta=new_meta(kind=EnvelopeKind.EVENT, source="test", principal="operator"),
            payload=RouteNotificationResult(
                decision="sent",
                delivered=True,
                detail="ok",
            ),
        )

    def flush_batch(self, *, meta, **kwargs):
        del meta, kwargs
        return success(
            meta=new_meta(kind=EnvelopeKind.EVENT, source="test", principal="operator"),
            payload=RouteNotificationResult(
                decision="sent",
                delivered=True,
                detail="ok",
            ),
        )

    def health(self, *, meta):
        del meta
        return success(
            meta=new_meta(kind=EnvelopeKind.EVENT, source="test", principal="operator"),
            payload=AttentionRouterHealthStatus(
                service_ready=True,
                adapter_ready=True,
                detail="ok",
            ),
        )

    def correlate_approval_response(self, *, meta, **kwargs):
        del meta
        return success(
            meta=new_meta(kind=EnvelopeKind.EVENT, source="test", principal="operator"),
            payload=RouterApprovalCorrelationPayload(
                actor=kwargs.get("actor", "operator"),
                channel=kwargs.get("channel", "signal"),
                message_text=kwargs.get("message_text", ""),
                approval_token=kwargs.get("approval_token", ""),
                reply_to_proposal_token=kwargs.get("reply_to_proposal_token", ""),
                reaction_to_proposal_token=kwargs.get("reaction_to_proposal_token", ""),
            ),
        )


def _request(
    *,
    envelope_id: str = "env-1",
    approval_token: str = "",
    actor: str = "operator",
    channel: str = "signal",
    capability_id: str = "demo-ping",
    autonomy: int = 0,
    requires_approval: bool = False,
    message_text: str = "",
) -> CapabilityInvocationRequest:
    return CapabilityInvocationRequest(
        metadata=new_meta(
            kind=EnvelopeKind.COMMAND,
            source="test",
            principal="operator",
            envelope_id=envelope_id,
            trace_id="trace-1",
        ),
        capability=CapabilityPolicyInput(
            capability_id=capability_id,
            kind="op",
            version="1.0.0",
            autonomy=autonomy,
            requires_approval=requires_approval,
        ),
        invocation=InvocationPolicyInput(
            actor=actor,
            source="agent",
            channel=channel,
            invocation_id="inv-1",
            approval_token=approval_token,
            message_text=message_text,
        ),
        input_payload={"ping": "pong"},
    )


def _settings_for_rule(rule: PolicyRule) -> PolicyServiceSettings:
    return PolicyServiceSettings(
        base_policy=PolicyDocument(
            policy_id="policy-core",
            policy_version="1",
            rules={"demo-ping": rule},
        )
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


def test_disabled_capability_denied() -> None:
    service = DefaultPolicyService(
        settings=_settings_for_rule(PolicyRule(enabled=False))
    )

    result = service.authorize_and_execute(
        request=_request(),
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )

    assert result.allowed is False
    assert "capability_disabled" in result.decision.reason_codes


def test_actor_and_channel_denial() -> None:
    service = DefaultPolicyService(
        settings=_settings_for_rule(
            PolicyRule(actors_deny=("operator",), channels_deny=("signal",))
        )
    )

    result = service.authorize_and_execute(
        request=_request(),
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )

    assert result.allowed is False
    assert "actor_denied" in result.decision.reason_codes
    assert "channel_denied" in result.decision.reason_codes


def test_autonomy_ceiling_denial() -> None:
    service = DefaultPolicyService(
        settings=_settings_for_rule(PolicyRule(autonomy_ceiling=1))
    )

    result = service.authorize_and_execute(
        request=_request(autonomy=2),
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )

    assert result.allowed is False
    assert "autonomy_exceeds_limit" in result.decision.reason_codes


def test_approval_required_emits_proposal_and_denies() -> None:
    service = DefaultPolicyService(settings=PolicyServiceSettings())
    req = _request(requires_approval=True)

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


def test_approval_required_routes_proposal_via_attention_router() -> None:
    router = _FakeAttentionRouterService()
    service = DefaultPolicyService(
        settings=PolicyServiceSettings(),
        attention_router_service=router,
    )
    req = _request(requires_approval=True)

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
    assert len(router.approval_payloads) == 1
    assert router.approval_payloads[0].proposal_token == result.proposal.proposal_token


def test_approval_notification_failure_is_reflected_in_reason_codes() -> None:
    router = _FakeAttentionRouterService()
    router.fail_approval_routing = True
    service = DefaultPolicyService(
        settings=PolicyServiceSettings(),
        attention_router_service=router,
    )
    req = _request(requires_approval=True)

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
    assert "approval_notification_failed" in result.decision.reason_codes


def test_valid_approval_token_allows_execution() -> None:
    service = DefaultPolicyService(settings=PolicyServiceSettings())
    base = _request(requires_approval=True)
    pending = service.authorize_and_execute(
        request=base,
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )
    assert pending.proposal is not None

    token = pending.proposal.proposal_token
    approved_request = _request(
        envelope_id="env-2",
        approval_token=token,
        requires_approval=True,
    )
    approved_request = approved_request.model_copy(
        update={
            "invocation": approved_request.invocation.model_copy(
                update={"invocation_id": "inv-2"}
            )
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


def test_reply_token_deterministic_correlation_allows_execution() -> None:
    service = DefaultPolicyService(settings=PolicyServiceSettings())
    pending = service.authorize_and_execute(
        request=_request(requires_approval=True),
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )
    assert pending.proposal is not None
    linked = _request(envelope_id="env-linked", requires_approval=True).model_copy(
        update={
            "invocation": InvocationPolicyInput(
                actor="operator",
                source="agent",
                channel="signal",
                invocation_id="inv-linked",
                reply_to_proposal_token=pending.proposal.proposal_token,
            )
        }
    )
    approved = service.authorize_and_execute(
        request=linked,
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )
    assert approved.allowed is True


def test_reaction_token_deterministic_correlation_allows_execution() -> None:
    service = DefaultPolicyService(settings=PolicyServiceSettings())
    pending = service.authorize_and_execute(
        request=_request(requires_approval=True),
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )
    assert pending.proposal is not None
    linked = _request(envelope_id="env-react", requires_approval=True).model_copy(
        update={
            "invocation": InvocationPolicyInput(
                actor="operator",
                source="agent",
                channel="signal",
                invocation_id="inv-react",
                reaction_to_proposal_token=pending.proposal.proposal_token,
            )
        }
    )
    approved = service.authorize_and_execute(
        request=linked,
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )
    assert approved.allowed is True


def test_ambiguous_multi_proposal_reply_denied() -> None:
    service = DefaultPolicyService(settings=PolicyServiceSettings())

    for envelope_id in ("env-a", "env-b"):
        service.authorize_and_execute(
            request=_request(
                envelope_id=envelope_id,
                requires_approval=True,
                capability_id=f"demo-ping-{envelope_id}",
            ),
            execute=lambda _: PolicyExecutionResult(
                allowed=True,
                output={"ok": True},
                errors=(),
                decision=_decision(),
            ),
        )

    ambiguous = service.authorize_and_execute(
        request=_request(
            envelope_id="env-c",
            requires_approval=True,
            message_text="approve",
            capability_id="demo-ping-env-a",
        ),
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )

    assert ambiguous.allowed is False
    assert "approval_required" in ambiguous.decision.reason_codes


def test_single_pending_proposal_approve_text_allows_execution() -> None:
    service = DefaultPolicyService(settings=PolicyServiceSettings())
    pending = service.authorize_and_execute(
        request=_request(requires_approval=True),
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )
    assert pending.proposal is not None

    approved = service.authorize_and_execute(
        request=_request(
            envelope_id="env-approve-text",
            requires_approval=True,
            message_text="approve",
        ).model_copy(
            update={
                "invocation": InvocationPolicyInput(
                    actor="operator",
                    source="agent",
                    channel="signal",
                    invocation_id="inv-approve-text",
                    message_text="approve",
                )
            }
        ),
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )

    assert approved.allowed is True
    assert approved.output == {"ok": True}


def test_low_confidence_disambiguation_requests_clarification() -> None:
    service = DefaultPolicyService(settings=PolicyServiceSettings())
    pending = service.authorize_and_execute(
        request=_request(requires_approval=True),
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )
    assert pending.proposal is not None

    second = service.authorize_and_execute(
        request=_request(
            envelope_id="env-clarify",
            requires_approval=True,
            capability_id="demo-ping",
        ).model_copy(
            update={
                "input_payload": {
                    "_policy_disambiguation": [
                        {
                            "proposal_token": pending.proposal.proposal_token,
                            "confidence": 0.70,
                        }
                    ]
                }
            }
        ),
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )

    assert second.allowed is False
    assert "approval_clarification_required" in second.decision.reason_codes


def test_disambiguation_at_auto_bind_threshold_allows_execution() -> None:
    service = DefaultPolicyService(settings=PolicyServiceSettings())
    pending = service.authorize_and_execute(
        request=_request(requires_approval=True),
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )
    assert pending.proposal is not None

    approved = service.authorize_and_execute(
        request=_request(
            envelope_id="env-bind-threshold",
            requires_approval=True,
        ).model_copy(
            update={
                "input_payload": {
                    "_policy_disambiguation": [
                        {
                            "proposal_token": pending.proposal.proposal_token,
                            "confidence": 0.90,
                        }
                    ]
                },
                "invocation": InvocationPolicyInput(
                    actor="operator",
                    source="agent",
                    channel="signal",
                    invocation_id="inv-bind-threshold",
                ),
            }
        ),
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )

    assert approved.allowed is True
    assert approved.output == {"ok": True}


def test_second_clarification_turn_becomes_ambiguous() -> None:
    service = DefaultPolicyService(settings=PolicyServiceSettings())
    pending = service.authorize_and_execute(
        request=_request(requires_approval=True),
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )
    assert pending.proposal is not None

    def _clarify(envelope_id: str) -> PolicyExecutionResult:
        return service.authorize_and_execute(
            request=_request(
                envelope_id=envelope_id,
                requires_approval=True,
            ).model_copy(
                update={
                    "input_payload": {
                        "_policy_disambiguation": [
                            {
                                "proposal_token": pending.proposal.proposal_token,
                                "confidence": 0.70,
                            }
                        ]
                    }
                }
            ),
            execute=lambda _: PolicyExecutionResult(
                allowed=True,
                output={"ok": True},
                errors=(),
                decision=_decision(),
            ),
        )

    first = _clarify("env-clarify-1")
    second = _clarify("env-clarify-2")
    assert first.allowed is False
    assert "approval_clarification_required" in first.decision.reason_codes
    assert second.allowed is False
    assert "approval_ambiguous" in second.decision.reason_codes


def test_policy_overlay_last_wins_and_unset() -> None:
    settings = PolicyServiceSettings(
        base_policy=PolicyDocument(
            policy_id="policy-core",
            policy_version="1",
            rules={"demo-ping": PolicyRule(enabled=False, channels_allow=("signal",))},
        ),
        overlays=(
            PolicyOverlay(
                name="001-enable",
                rules={"demo-ping": PolicyRuleOverlay(enabled=True)},
            ),
            PolicyOverlay(
                name="002-unset-channel", unset=("rules.demo-ping.channels_allow",)
            ),
        ),
    )

    service = DefaultPolicyService(settings=settings)
    result = service.authorize_and_execute(
        request=_request(),
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )

    assert result.allowed is True


def test_decision_contains_policy_regime_id() -> None:
    service = DefaultPolicyService(settings=PolicyServiceSettings())
    result = service.authorize_and_execute(
        request=_request(),
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )

    assert result.decision.policy_regime_id != ""


def test_health_reports_regime_and_counter_state() -> None:
    service = DefaultPolicyService(settings=PolicyServiceSettings())
    meta = new_meta(kind=EnvelopeKind.RESULT, source="test", principal="operator")
    health = service.health(meta=meta)
    assert health.ok is True
    assert health.payload is not None
    assert health.payload.value.active_policy_regime_id != ""
    assert health.payload.value.regime_rows >= 1


def test_service_writes_decisions_and_proposals_to_injected_repository() -> None:
    repo = InMemoryPolicyPersistenceRepository()
    service = DefaultPolicyService(settings=PolicyServiceSettings(), persistence=repo)
    service.authorize_and_execute(
        request=_request(requires_approval=True),
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )
    assert repo.count_decisions() == 1
    assert repo.count_proposals() == 1


def test_unknown_capability_is_denied_without_wildcard_rule() -> None:
    service = DefaultPolicyService(
        settings=PolicyServiceSettings(
            base_policy=PolicyDocument(
                policy_id="policy-core",
                policy_version="1",
                rules={"demo-known": PolicyRule()},
            )
        )
    )
    result = service.authorize_and_execute(
        request=_request(capability_id="demo-unknown"),
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )
    assert result.allowed is False
    assert "unknown_call_target" in result.decision.reason_codes


def test_request_schema_validation_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        CapabilityInvocationRequest.model_validate(
            {
                "metadata": new_meta(
                    kind=EnvelopeKind.COMMAND,
                    source="test",
                    principal="operator",
                ).model_dump(mode="python"),
                "capability": {
                    "capability_id": "demo-ping",
                    "kind": "op",
                    "version": "1.0.0",
                    "autonomy": 0,
                    "requires_approval": False,
                },
                "invocation": {
                    "actor": "operator",
                    "source": "agent",
                    "channel": "signal",
                    "invocation_id": "inv-1",
                },
                "input_payload": {"ping": "pong"},
                "unexpected": True,
            }
        )


def test_approval_notification_payload_is_token_only() -> None:
    service = DefaultPolicyService(settings=PolicyServiceSettings())
    pending = service.authorize_and_execute(
        request=_request(requires_approval=True),
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )
    assert pending.proposal is not None
    notification = ApprovalNotificationPayload(
        proposal_token=pending.proposal.proposal_token,
        capability_id=pending.proposal.capability_id,
        capability_version=pending.proposal.capability_version,
        summary=pending.proposal.summary,
        actor=pending.proposal.actor,
        channel=pending.proposal.channel,
        trace_id=pending.proposal.trace_id,
        invocation_id=pending.proposal.invocation_id,
        expires_at=pending.proposal.expires_at,
    )
    assert notification.proposal_token != ""
    assert notification.summary != ""


def test_approval_correlation_payload_maps_to_invocation_fields() -> None:
    payload = ApprovalCorrelationPayload(
        actor="operator",
        channel="signal",
        message_text="approve",
        reply_to_proposal_token="token-1",
    )
    invocation = InvocationPolicyInput(
        actor=payload.actor,
        source="agent",
        channel=payload.channel,
        invocation_id="inv-2",
        message_text=payload.message_text,
        approval_token=payload.approval_token,
        reply_to_proposal_token=payload.reply_to_proposal_token,
        reaction_to_proposal_token=payload.reaction_to_proposal_token,
    )
    assert invocation.reply_to_proposal_token == "token-1"
