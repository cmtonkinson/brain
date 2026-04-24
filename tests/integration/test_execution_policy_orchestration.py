"""Cross-service orchestration tests for Execution->Policy interaction."""

from __future__ import annotations

from pathlib import Path

from lib.shared.envelope import EnvelopeKind, new_meta
from services.effect.execution.config import ExecutionSettings
from services.effect.execution.data.repository import (
    InMemoryOpInvocationAuditRepository,
)
from services.effect.execution.domain import (
    OpExecutionResponse,
    OpInvocationMetadata,
    NativeOpManifest,
)
from services.effect.execution.implementation import (
    DefaultExecutionService,
)
from services.effect.execution.registry import OpRegistry
from services.reason.policy.config import PolicyServiceSettings
from services.reason.policy.implementation import DefaultPolicyService


def _meta():
    """Build deterministic metadata for integration calls."""
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def test_ces_invocation_routes_through_policy_and_audit() -> None:
    """Execution should route invoke through Policy and append one audit row."""
    policy = DefaultPolicyService(settings=PolicyServiceSettings())
    registry = OpRegistry()
    registry.register_manifest(
        manifest=NativeOpManifest(
            op_id="demo-echo",
            kind="native",
            version="1.0.0",
            summary="Echo",
            input_schema={
                "component_id": "string | The component identifier.",
                "key": "string | The cache key.",
            },
            output_schema=None,
            call_target="service_cache.get_value",
        )
    )
    registry.register_handler(
        op_id="demo-echo",
        handler=lambda _request, _runtime: OpExecutionResponse(output={"ok": True}),
    )
    audit = InMemoryOpInvocationAuditRepository()
    service = DefaultExecutionService(
        settings=ExecutionSettings(discovery_roots=(str(Path("ops")),)),
        policy_service=policy,
        registry=registry,
        audit_repository=audit,
    )

    result = service.invoke_op(
        meta=_meta(),
        op_id="demo-echo",
        input_payload={"x": 1},
        invocation=OpInvocationMetadata(
            actor="operator",
            source="assistant",
            channel="signal",
            invocation_id="inv-1",
            parent_invocation_id="",
        ),
    )

    assert result.ok is True
    assert audit.count() == 1
