"""Cross-service orchestration tests for CES->PS interaction."""

from __future__ import annotations

from pathlib import Path

from packages.brain_shared.envelope import EnvelopeKind, new_meta
from services.action.capability_engine.config import CapabilityEngineSettings
from services.action.capability_engine.data.repository import (
    InMemoryCapabilityInvocationAuditRepository,
)
from services.action.capability_engine.domain import (
    CapabilityExecutionResponse,
    CapabilityInvocationMetadata,
    OpCapabilityManifest,
)
from services.action.capability_engine.implementation import (
    DefaultCapabilityEngineService,
)
from services.action.capability_engine.registry import CapabilityRegistry
from services.action.policy_service.config import PolicyServiceSettings
from services.action.policy_service.implementation import DefaultPolicyService


def _meta():
    """Build deterministic metadata for integration calls."""
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def test_ces_invocation_routes_through_policy_and_audit() -> None:
    """CES should route invoke through PS and append one audit row."""
    policy = DefaultPolicyService(settings=PolicyServiceSettings())
    registry = CapabilityRegistry()
    registry.register_manifest(
        manifest=OpCapabilityManifest(
            capability_id="demo-echo",
            kind="op",
            version="1.0.0",
            summary="Echo",
            input_types=("dict[str, object]",),
            output_types=("dict[str, object]",),
            call_target="service_cache_authority.get_value",
        )
    )
    registry.register_handler(
        capability_id="demo-echo",
        handler=lambda _request, _runtime: CapabilityExecutionResponse(
            output={"ok": True}
        ),
    )
    audit = InMemoryCapabilityInvocationAuditRepository()
    service = DefaultCapabilityEngineService(
        settings=CapabilityEngineSettings(discovery_root=str(Path("capabilities"))),
        policy_service=policy,
        registry=registry,
        audit_repository=audit,
    )

    result = service.invoke_capability(
        meta=_meta(),
        capability_id="demo-echo",
        input_payload={"x": 1},
        invocation=CapabilityInvocationMetadata(
            actor="operator",
            source="agent",
            channel="signal",
            invocation_id="inv-1",
            parent_invocation_id="",
        ),
    )

    assert result.ok is True
    assert audit.count() == 1
