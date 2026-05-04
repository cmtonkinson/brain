"""Unit tests for Policy Service authorization behaviors."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from lib.shared.envelope import EnvelopeKind, failure, new_meta, success
from lib.shared.errors import dependency_error
from services.effect.relay._outbound.domain import (
    HealthStatus as RelayOutboundHealthStatus,
)
from services.effect.relay.domain import (
    ApprovalCorrelationPayload,
    ApprovalNotificationPayload,
    RouteNotificationResult,
)
from services.effect.relay.service import RelayService
from services.reason.policy.config import PolicyServiceSettings
from services.reason.policy.data.repository import (
    InMemoryPolicyPersistenceRepository,
)
from services.reason.policy.domain import (
    OpInvocationRequest,
    OpPolicyInput,
    InvocationPolicyInput,
    PolicyDecision,
    PolicyDocument,
    PolicyExecutionResult,
    PolicyOverlay,
    PolicyRule,
    PolicyRuleOverlay,
)
from services.reason.policy.implementation import DefaultPolicyService


def _decision() -> PolicyDecision:
    return PolicyDecision(
        decision_id="tmp",
        policy_regime_id="regime-1",
        policy_regime_hash="hash-1",
        allowed=True,
        reason_codes=(),
        obligations=(),
        policy_metadata={},
        decided_at=datetime.now(UTC),
        policy_name="tmp",
        policy_version="1",
    )


class _FakeRelayOutboundService(RelayService):
    """Test double for Policy Service approval-notification routing calls."""

    def __init__(self) -> None:
        self.approval_payloads: list[ApprovalNotificationPayload] = []
        self.approval_metas: list[object] = []
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
        self.approval_metas.append(meta)
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
            payload=RelayOutboundHealthStatus(
                service_ready=True,
                adapter_ready=True,
                detail="ok",
            ),
        )

    def correlate_approval_response(self, *, meta, **kwargs):
        del meta
        return success(
            meta=new_meta(kind=EnvelopeKind.EVENT, source="test", principal="operator"),
            payload=ApprovalCorrelationPayload(
                actor=kwargs.get("actor", "operator"),
                channel=kwargs.get("channel", "signal"),
                message_text=kwargs.get("message_text", ""),
                approval_token=kwargs.get("approval_token", ""),
                reply_to_proposal_token=kwargs.get("reply_to_proposal_token", ""),
                reaction_to_proposal_token=kwargs.get("reaction_to_proposal_token", ""),
            ),
        )

    def resolve_approval_notification_proposal_token(
        self,
        *,
        meta,
        channel: str,
        target_timestamp_ms: int,
    ):
        del meta, channel, target_timestamp_ms
        return success(
            meta=new_meta(kind=EnvelopeKind.EVENT, source="test", principal="operator"),
            payload=None,
        )

    def poll_console_response(self, *, meta, wait_timeout_seconds: float = 0.0):
        del meta, wait_timeout_seconds
        return success(
            meta=new_meta(kind=EnvelopeKind.EVENT, source="test", principal="operator"),
            payload=None,
        )

    def ingest_signal_message(self, *, meta, raw_body_json: str):
        del meta, raw_body_json
        raise NotImplementedError

    def enqueue_console_message(self, *, meta, message_text: str):
        del meta, message_text
        raise NotImplementedError

    def register_signal_callback(self, *, meta):
        del meta
        raise NotImplementedError

    def poll_operator_instruction(self, *, meta, wait_timeout_seconds: float = 0.0):
        del meta, wait_timeout_seconds
        raise NotImplementedError


def _request(
    *,
    envelope_id: str = "env-1",
    approval_token: str = "",
    actor: str = "operator",
    channel: str = "signal",
    op_id: str = "demo-ping",
    effect: str = "read",
    approval: str = "never",
    message_text: str = "",
) -> OpInvocationRequest:
    return OpInvocationRequest(
        metadata=new_meta(
            kind=EnvelopeKind.COMMAND,
            source="test",
            principal="operator",
            envelope_id=envelope_id,
            trace_id="trace-1",
        ),
        op_policy=OpPolicyInput(
            op_id=op_id,
            kind="op",
            version="1.0.0",
            effect=effect,
            approval=approval,
        ),
        invocation=InvocationPolicyInput(
            actor=actor,
            source="assistant",
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


def test_disabled_op_denied() -> None:
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
    assert "op_disabled" in result.decision.reason_codes


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


def test_approval_required_emits_proposal_and_denies() -> None:
    service = DefaultPolicyService(settings=PolicyServiceSettings())
    req = _request(approval="always")

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
    assert result.errors[0].metadata["proposal_token"] == result.proposal.proposal_token
    assert (
        result.errors[0].metadata["expires_at"]
        == result.proposal.expires_at.isoformat()
    )


def test_approval_required_routes_proposal_via_outbound() -> None:
    router = _FakeRelayOutboundService()
    service = DefaultPolicyService(
        settings=PolicyServiceSettings(),
        outbound_service=router,
    )
    req = _request(approval="always")

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
    assert len(router.approval_metas) == 1
    assert router.approval_payloads[0].proposal_token == result.proposal.proposal_token
    assert router.approval_metas[0].trace_id == req.metadata.trace_id
    assert router.approval_metas[0].parent_id == req.metadata.envelope_id
    assert router.approval_metas[0].envelope_id != req.metadata.envelope_id


def test_approval_notification_failure_is_reflected_in_reason_codes() -> None:
    router = _FakeRelayOutboundService()
    router.fail_approval_routing = True
    service = DefaultPolicyService(
        settings=PolicyServiceSettings(),
        outbound_service=router,
    )
    req = _request(approval="always")

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


def test_text_approval_ignores_expired_pending_proposals() -> None:
    service = DefaultPolicyService(
        settings=_settings_for_rule(PolicyRule(approval="always"))
    )
    expired = service.authorize_and_execute(
        request=_request(
            envelope_id="env-expired",
            approval="always",
            op_id="demo-ping",
        ),
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )
    assert expired.proposal is not None
    service._persistence.mark_proposal_status(  # type: ignore[attr-defined]
        token=expired.proposal.proposal_token,
        status="expired",
    )

    pending = service.authorize_and_execute(
        request=_request(
            envelope_id="env-pending",
            approval="always",
            op_id="demo-ping",
        ),
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
            envelope_id="env-approved",
            approval="always",
            op_id="demo-ping",
            message_text="approve",
        ),
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )

    assert approved.allowed is True


def test_valid_approval_token_allows_execution() -> None:
    service = DefaultPolicyService(settings=PolicyServiceSettings())
    base = _request(approval="always")
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
        approval="always",
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
        request=_request(approval="always"),
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )
    assert pending.proposal is not None
    linked = _request(envelope_id="env-linked", approval="always").model_copy(
        update={
            "invocation": InvocationPolicyInput(
                actor="operator",
                source="assistant",
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
        request=_request(approval="always"),
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )
    assert pending.proposal is not None
    linked = _request(envelope_id="env-react", approval="always").model_copy(
        update={
            "invocation": InvocationPolicyInput(
                actor="operator",
                source="assistant",
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
                approval="always",
                op_id=f"demo-ping-{envelope_id}",
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
            approval="always",
            message_text="approve",
            op_id="demo-ping-env-a",
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
        request=_request(approval="always"),
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
            approval="always",
            message_text="approve",
        ).model_copy(
            update={
                "invocation": InvocationPolicyInput(
                    actor="operator",
                    source="assistant",
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


def test_single_pending_proposal_approved_text_allows_execution() -> None:
    service = DefaultPolicyService(settings=PolicyServiceSettings())
    pending = service.authorize_and_execute(
        request=_request(approval="always"),
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
            envelope_id="env-approved-text",
            approval="always",
            message_text="approved",
        ).model_copy(
            update={
                "invocation": InvocationPolicyInput(
                    actor="operator",
                    source="assistant",
                    channel="signal",
                    invocation_id="inv-approved-text",
                    message_text="approved",
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
        request=_request(approval="always"),
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
            approval="always",
            op_id="demo-ping",
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
        request=_request(approval="always"),
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
            approval="always",
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
                    source="assistant",
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
        request=_request(approval="always"),
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
                approval="always",
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
        request=_request(approval="always"),
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )
    assert repo.count_decisions() == 1
    assert repo.count_proposals() == 1


def test_unknown_op_is_denied_without_wildcard_rule() -> None:
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
        request=_request(op_id="demo-unknown"),
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
        OpInvocationRequest.model_validate(
            {
                "metadata": new_meta(
                    kind=EnvelopeKind.COMMAND,
                    source="test",
                    principal="operator",
                ).model_dump(mode="python"),
                "op": {
                    "op_id": "demo-ping",
                    "kind": "op",
                    "version": "1.0.0",
                    "effect": "read",
                    "approval": "never",
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
        request=_request(approval="always"),
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
        op_id=pending.proposal.op_id,
        op_version=pending.proposal.op_version,
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
        source="assistant",
        channel=payload.channel,
        invocation_id="inv-2",
        message_text=payload.message_text,
        approval_token=payload.approval_token,
        reply_to_proposal_token=payload.reply_to_proposal_token,
        reaction_to_proposal_token=payload.reaction_to_proposal_token,
    )
    assert invocation.reply_to_proposal_token == "token-1"


# ---------------------------------------------------------------------------
# Slash authenticity proof
# ---------------------------------------------------------------------------


def _seed_authenticity_secret(tmp_path) -> bytes:
    """Write a known secret at the XDG-resolved path and return its bytes."""
    from lib.shared.auth.slash_authenticity import generate_and_write_secret

    secret_path = tmp_path / "brain" / "slash_authenticity_secret"
    return generate_and_write_secret(secret_path)


_SLASH_TEXT = "/workspace-register --path /tmp/foo"


def _slash_request(
    *,
    proof,
    message_text: str = _SLASH_TEXT,
    channel: str = "console",
    op_id: str = "demo-ping",
    approval: str = "always",
    envelope_id: str = "env-slash-1",
    invocation_id: str = "inv-slash-1",
) -> OpInvocationRequest:
    """Build an OpInvocationRequest carrying a slash_authenticity proof."""
    return OpInvocationRequest(
        metadata=new_meta(
            kind=EnvelopeKind.COMMAND,
            source="test",
            principal="operator",
            envelope_id=envelope_id,
            trace_id="trace-1",
        ),
        op_policy=OpPolicyInput(
            op_id=op_id,
            kind="op",
            version="1.0.0",
            effect="write",
            approval=approval,
        ),
        invocation=InvocationPolicyInput(
            actor="operator",
            source="console",
            channel=channel,
            invocation_id=invocation_id,
            message_text=message_text,
            slash_authenticity=proof,
        ),
        input_payload={"path": "/tmp/foo"},
    )


def test_valid_slash_authenticity_allows_execution(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A correct HMAC bypasses the approval gate on an `approval: always` op."""
    from lib.shared.auth.slash_authenticity import mint_proof, new_nonce

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    secret = _seed_authenticity_secret(tmp_path)
    proof = mint_proof(
        secret,
        channel="console",
        message_text=_SLASH_TEXT,
        now_ms=int(datetime.now(UTC).timestamp() * 1000),
        nonce=new_nonce(),
    )

    service = DefaultPolicyService(settings=PolicyServiceSettings())
    result = service.authorize_and_execute(
        request=_slash_request(proof=proof),
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )
    assert result.allowed is True
    assert result.output == {"ok": True}


def test_invalid_slash_authenticity_denies(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A tampered HMAC is rejected and the reason code surfaces."""
    from lib.shared.auth.slash_authenticity import (
        SlashAuthenticityProof,
        mint_proof,
        new_nonce,
    )

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    secret = _seed_authenticity_secret(tmp_path)
    minted = mint_proof(
        secret,
        channel="console",
        message_text=_SLASH_TEXT,
        now_ms=int(datetime.now(UTC).timestamp() * 1000),
        nonce=new_nonce(),
    )
    tampered = SlashAuthenticityProof(
        hmac_b64="A" * 43,  # well-formed base64 of wrong bytes
        timestamp_ms=minted.timestamp_ms,
        nonce=minted.nonce,
    )

    service = DefaultPolicyService(settings=PolicyServiceSettings())
    result = service.authorize_and_execute(
        request=_slash_request(proof=tampered),
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )
    assert result.allowed is False
    assert "slash_authenticity_invalid" in result.decision.reason_codes


def test_replayed_slash_authenticity_nonce_denies(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Re-using a nonce within the validity window fails."""
    from lib.shared.auth.slash_authenticity import mint_proof

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    secret = _seed_authenticity_secret(tmp_path)
    proof = mint_proof(
        secret,
        channel="console",
        message_text=_SLASH_TEXT,
        now_ms=int(datetime.now(UTC).timestamp() * 1000),
        nonce="fixed-nonce",
    )

    service = DefaultPolicyService(settings=PolicyServiceSettings())
    first = service.authorize_and_execute(
        request=_slash_request(proof=proof),
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )
    assert first.allowed is True

    replay = service.authorize_and_execute(
        request=_slash_request(
            proof=proof,
            envelope_id="env-slash-2",
            invocation_id="inv-slash-2",
        ),
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )
    assert replay.allowed is False
    assert "slash_authenticity_invalid" in replay.decision.reason_codes


def test_missing_slash_authenticity_falls_through_to_proposal() -> None:
    """No proof present means standard `approval: always` flow runs."""
    service = DefaultPolicyService(settings=PolicyServiceSettings())
    result = service.authorize_and_execute(
        request=_request(approval="always"),
        execute=lambda _: PolicyExecutionResult(
            allowed=True,
            output={"ok": True},
            errors=(),
            decision=_decision(),
        ),
    )
    assert result.allowed is False
    assert result.proposal is not None
