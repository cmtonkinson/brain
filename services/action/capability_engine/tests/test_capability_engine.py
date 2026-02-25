"""Unit tests for Capability Engine policy integration behavior."""

from __future__ import annotations

from typing import Any

from packages.brain_shared.envelope import EnvelopeKind, failure, new_meta, success
from packages.brain_shared.errors import policy_error
from services.action.capability_engine.config import CapabilityEngineSettings
from services.action.capability_engine.domain import (
    CapabilityEngineHealthStatus,
    CapabilityExecutionResponse,
    CapabilityIdentity,
    CapabilityPolicyContext,
    CapabilitySpec,
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

    def authorize_and_execute(
        self,
        *,
        request: CapabilityInvocationRequest,
        execute: PolicyExecuteCallback,
    ) -> PolicyExecutionResult:
        self.calls += 1
        callback = execute(request)
        return callback.model_copy(update={"decision": _allow_decision()})

    def health(self, *, meta: Any):
        return success(
            meta=meta,
            payload=PolicyHealthStatus(
                service_ready=True,
                decision_log_rows=0,
                proposal_rows=0,
                dedupe_rows=0,
                detail="ok",
            ),
        )


def _allow_decision() -> PolicyDecision:
    return PolicyDecision(
        decision_id="decision",
        allowed=True,
        reason_codes=(),
        obligations=(),
        policy_metadata={},
        decided_at=utc_now(),
        policy_name="test",
        policy_version="1",
    )


def _policy_context() -> CapabilityPolicyContext:
    return CapabilityPolicyContext(
        actor="operator",
        channel="signal",
        invocation_id="inv-1",
    )


def test_ces_invocation_routes_through_policy_wrapper() -> None:
    registry = CapabilityRegistry()
    spec = CapabilitySpec(
        kind="op",
        namespace="demo",
        name="echo",
        version="v1",
    )
    registry.register_spec(spec=spec)
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
        capability=CapabilityIdentity(
            kind="op",
            namespace="demo",
            name="echo",
            version="v1",
        ),
        input_payload={"text": "hello"},
        policy_context=_policy_context(),
    )

    assert result.ok is True
    assert policy.calls == 1
    assert result.payload is not None
    assert result.payload.value.output == {"echo": "hello"}


def test_nested_capability_invocation_re_authorizes_child() -> None:
    registry = CapabilityRegistry()
    child = CapabilitySpec(kind="op", namespace="demo", name="child", version="v1")
    parent = CapabilitySpec(kind="skill", namespace="demo", name="parent", version="v1")
    registry.register_spec(spec=child)
    registry.register_spec(spec=parent)

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
            kind="op",
            namespace="demo",
            name="child",
            version="v1",
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
        capability=CapabilityIdentity(
            kind="skill",
            namespace="demo",
            name="parent",
            version="v1",
        ),
        input_payload={},
        policy_context=_policy_context(),
    )

    assert result.ok is True
    assert policy.calls == 2


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
