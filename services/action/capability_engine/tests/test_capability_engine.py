"""Unit tests for Capability Engine policy integration behavior."""

from __future__ import annotations

from typing import Any

from packages.brain_shared.envelope import EnvelopeKind, failure, new_meta, success
from packages.brain_shared.errors import policy_error
from services.action.capability_engine.config import CapabilityEngineSettings
from services.action.capability_engine.data.repository import (
    InMemoryCapabilityInvocationAuditRepository,
)
from services.action.capability_engine.domain import (
    CapabilityEngineHealthStatus,
    CapabilityExecutionResponse,
    CapabilityInvocationMetadata,
    OpCapabilityManifest,
    SkillCapabilityManifest,
)
from services.action.capability_engine.implementation import (
    DefaultCapabilityEngineService,
)
from services.action.capability_engine.registry import (
    CapabilityRegistry,
    CapabilityRuntime,
)
from services.action.policy_service.domain import (
    CapabilityInvocationRequest,
    PolicyDecision,
    PolicyExecutionResult,
    PolicyHealthStatus,
    utc_now,
)
from services.action.policy_service.service import PolicyExecuteCallback, PolicyService


class _FakePolicyService(PolicyService):
    def __init__(self) -> None:
        self.calls = 0
        self.requests: list[CapabilityInvocationRequest] = []

    def authorize_and_execute(
        self,
        *,
        request: CapabilityInvocationRequest,
        execute: PolicyExecuteCallback,
    ) -> PolicyExecutionResult:
        self.calls += 1
        self.requests.append(request)
        callback = execute(request)
        return callback.model_copy(update={"decision": _allow_decision()})

    def health(self, *, meta: Any):
        return success(
            meta=meta,
            payload=PolicyHealthStatus(
                service_ready=True,
                active_policy_regime_id="regime-1",
                regime_rows=1,
                decision_log_rows=0,
                proposal_rows=0,
                dedupe_rows=0,
                detail="ok",
            ),
        )


class _DenyingPolicyService(PolicyService):
    def authorize_and_execute(
        self,
        *,
        request: CapabilityInvocationRequest,
        execute: PolicyExecuteCallback,
    ) -> PolicyExecutionResult:
        return PolicyExecutionResult(
            allowed=False,
            output=None,
            errors=(
                policy_error(
                    "denied",
                    metadata={"reason_codes": "actor_denied"},
                ),
            ),
            decision=_allow_decision().model_copy(
                update={
                    "allowed": False,
                    "reason_codes": ("actor_denied",),
                }
            ),
            proposal=None,
        )

    def health(self, *, meta: Any):
        return success(
            meta=meta,
            payload=PolicyHealthStatus(
                service_ready=True,
                active_policy_regime_id="regime-1",
                regime_rows=1,
                decision_log_rows=0,
                proposal_rows=0,
                dedupe_rows=0,
                detail="ok",
            ),
        )


def _allow_decision() -> PolicyDecision:
    return PolicyDecision(
        decision_id="decision",
        policy_regime_id="regime-1",
        policy_regime_hash="hash-1",
        allowed=True,
        reason_codes=(),
        obligations=(),
        policy_metadata={},
        decided_at=utc_now(),
        policy_name="test",
        policy_version="1",
    )


def _invocation() -> CapabilityInvocationMetadata:
    return CapabilityInvocationMetadata(
        actor="operator",
        source="agent",
        channel="signal",
        invocation_id="inv-1",
    )


def test_ces_invocation_routes_through_policy_wrapper() -> None:
    registry = CapabilityRegistry()
    spec = OpCapabilityManifest(
        capability_id="demo-echo",
        kind="op",
        version="1.0.0",
        summary="Echo input",
        call_target="state.echo",
    )
    registry.register_manifest(manifest=spec)
    registry.register_handler(
        capability_id=spec.capability_id,
        handler=lambda request, runtime: CapabilityExecutionResponse(
            output={"echo": request.input_payload.get("text")}
        ),
    )

    policy = _FakePolicyService()
    service = DefaultCapabilityEngineService(
        settings=CapabilityEngineSettings(),
        policy_service=policy,
        registry=registry,
    )

    result = service.invoke_capability(
        meta=new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator"),
        capability_id="demo-echo",
        input_payload={"text": "hello"},
        invocation=_invocation(),
    )

    assert result.ok is True
    assert policy.calls == 1
    assert result.payload is not None
    assert result.payload.value.output == {"echo": "hello"}


def test_nested_capability_invocation_re_authorizes_child() -> None:
    registry = CapabilityRegistry()
    child = OpCapabilityManifest(
        capability_id="demo-child",
        kind="op",
        version="1.0.0",
        summary="Child op",
        call_target="state.child",
    )
    parent = SkillCapabilityManifest(
        capability_id="demo-parent",
        kind="skill",
        version="1.0.0",
        summary="Parent skill",
        skill_type="logic",
    )
    registry.register_manifest(manifest=child)
    registry.register_manifest(manifest=parent)

    registry.register_handler(
        capability_id=child.capability_id,
        handler=lambda request, runtime: CapabilityExecutionResponse(
            output={"child": request.input_payload.get("value")}
        ),
    )

    def parent_handler(
        request: CapabilityInvocationRequest,
        runtime: CapabilityRuntime,
    ) -> CapabilityExecutionResponse:
        nested = runtime.invoke_nested(
            capability_id="demo-child",
            input_payload={"value": "nested"},
        )
        return CapabilityExecutionResponse(output={"nested": nested.output})

    registry.register_handler(
        capability_id=parent.capability_id, handler=parent_handler
    )

    policy = _FakePolicyService()
    service = DefaultCapabilityEngineService(
        settings=CapabilityEngineSettings(),
        policy_service=policy,
        registry=registry,
    )

    result = service.invoke_capability(
        meta=new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator"),
        capability_id="demo-parent",
        input_payload={},
        invocation=_invocation(),
    )

    assert result.ok is True
    assert policy.calls == 2
    assert len(policy.requests) == 2
    assert (
        policy.requests[1].metadata.parent_id == policy.requests[0].metadata.envelope_id
    )
    assert policy.requests[1].metadata.trace_id == policy.requests[0].metadata.trace_id


def test_disabled_manifest_denied_without_policy_call() -> None:
    registry = CapabilityRegistry()
    spec = OpCapabilityManifest(
        capability_id="demo-disabled",
        kind="op",
        version="1.0.0",
        summary="Disabled",
        enabled=False,
        call_target="state.disabled",
    )
    registry.register_manifest(manifest=spec)

    policy = _FakePolicyService()
    service = DefaultCapabilityEngineService(
        settings=CapabilityEngineSettings(),
        policy_service=policy,
        registry=registry,
    )

    result = service.invoke_capability(
        meta=new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator"),
        capability_id="demo-disabled",
        input_payload={},
        invocation=_invocation(),
    )

    assert result.ok is False
    assert policy.calls == 0


def test_unknown_handler_fails_after_policy_wrapper() -> None:
    registry = CapabilityRegistry()
    spec = OpCapabilityManifest(
        capability_id="demo-no-handler",
        kind="op",
        version="1.0.0",
        summary="No handler",
        call_target="state.missing",
    )
    registry.register_manifest(manifest=spec)

    policy = _FakePolicyService()
    service = DefaultCapabilityEngineService(
        settings=CapabilityEngineSettings(),
        policy_service=policy,
        registry=registry,
    )

    result = service.invoke_capability(
        meta=new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator"),
        capability_id="demo-no-handler",
        input_payload={},
        invocation=_invocation(),
    )

    assert result.ok is False
    assert policy.calls == 1


def test_unknown_capability_id_returns_not_found() -> None:
    service = DefaultCapabilityEngineService(
        settings=CapabilityEngineSettings(),
        policy_service=_FakePolicyService(),
        registry=CapabilityRegistry(),
    )
    result = service.invoke_capability(
        meta=new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator"),
        capability_id="missing-capability",
        input_payload={},
        invocation=_invocation(),
    )
    assert result.ok is False


def test_policy_denial_propagates_reason_codes() -> None:
    registry = CapabilityRegistry()
    spec = OpCapabilityManifest(
        capability_id="demo-denied",
        kind="op",
        version="1.0.0",
        summary="Denied by policy",
        call_target="state.denied",
    )
    registry.register_manifest(manifest=spec)
    registry.register_handler(
        capability_id=spec.capability_id,
        handler=lambda request, runtime: CapabilityExecutionResponse(
            output={"ok": True}
        ),
    )
    service = DefaultCapabilityEngineService(
        settings=CapabilityEngineSettings(),
        policy_service=_DenyingPolicyService(),
        registry=registry,
    )
    result = service.invoke_capability(
        meta=new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator"),
        capability_id="demo-denied",
        input_payload={},
        invocation=_invocation(),
    )
    assert result.ok is False
    assert result.errors[0].metadata is not None
    assert "actor_denied" in result.errors[0].metadata["reason_codes"]


def test_invocation_audit_rows_capture_lineage_and_policy_fields() -> None:
    registry = CapabilityRegistry()
    spec = OpCapabilityManifest(
        capability_id="demo-audit",
        kind="op",
        version="1.0.0",
        summary="Audit probe",
        call_target="state.audit",
    )
    registry.register_manifest(manifest=spec)
    registry.register_handler(
        capability_id=spec.capability_id,
        handler=lambda request, runtime: CapabilityExecutionResponse(
            output={"ok": True}
        ),
    )
    audit_repo = InMemoryCapabilityInvocationAuditRepository()
    service = DefaultCapabilityEngineService(
        settings=CapabilityEngineSettings(),
        policy_service=_FakePolicyService(),
        registry=registry,
        audit_repository=audit_repo,
    )
    meta = new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")
    service.invoke_capability(
        meta=meta,
        capability_id="demo-audit",
        input_payload={},
        invocation=_invocation(),
    )
    row = audit_repo.list_rows()[-1]
    assert row.envelope_id == meta.envelope_id
    assert row.trace_id == meta.trace_id
    assert row.capability_id == "demo-audit"
    assert row.policy_regime_id == "regime-1"


def test_health_reflects_injected_audit_repository_count() -> None:
    registry = CapabilityRegistry()
    spec = OpCapabilityManifest(
        capability_id="demo-health-audit",
        kind="op",
        version="1.0.0",
        summary="Health audit probe",
        call_target="state.health",
    )
    registry.register_manifest(manifest=spec)
    registry.register_handler(
        capability_id=spec.capability_id,
        handler=lambda request, runtime: CapabilityExecutionResponse(
            output={"ok": True}
        ),
    )
    audit_repo = InMemoryCapabilityInvocationAuditRepository()
    service = DefaultCapabilityEngineService(
        settings=CapabilityEngineSettings(),
        policy_service=_FakePolicyService(),
        registry=registry,
        audit_repository=audit_repo,
    )

    service.invoke_capability(
        meta=new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator"),
        capability_id="demo-health-audit",
        input_payload={},
        invocation=_invocation(),
    )
    health = service.health(
        meta=new_meta(kind=EnvelopeKind.RESULT, source="test", principal="operator")
    )
    assert health.ok is True
    assert health.payload is not None
    assert health.payload.value.invocation_audit_rows == 1


def test_ces_health_reflects_policy_health() -> None:
    class _FailingPolicyService(_FakePolicyService):
        def health(self, *, meta: Any):
            return failure(meta=meta, errors=[policy_error("unhealthy")])

    service = DefaultCapabilityEngineService(
        settings=CapabilityEngineSettings(),
        policy_service=_FailingPolicyService(),
        registry=CapabilityRegistry(),
    )

    health = service.health(
        meta=new_meta(kind=EnvelopeKind.RESULT, source="test", principal="operator")
    )
    assert health.ok is True
    assert health.payload is not None
    payload: CapabilityEngineHealthStatus = health.payload.value
    assert payload.policy_ready is False
