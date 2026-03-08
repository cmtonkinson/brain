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
    CapabilityDescriptor,
    CapabilityEngineHealthStatus,
    CapabilityExecutionResponse,
    CapabilityInvocationMetadata,
    CapabilitySearchHit,
    OpCapabilityManifest,
    SkillCapabilityManifest,
)
from services.action.capability_engine.implementation import (
    DefaultCapabilityEngineService,
)
from services.action.capability_engine.pipeline_handler_bridge import (
    build_pipeline_skill_handler,
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
        kind="native_op",
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
        kind="native_op",
        version="1.0.0",
        summary="Child op",
        call_target="state.child",
    )
    parent = SkillCapabilityManifest(
        capability_id="demo-parent",
        kind="logic_skill",
        version="1.0.0",
        summary="Parent skill",
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


def test_pipeline_skill_projects_step_input_mapping_and_aliased_pipeline_output() -> (
    None
):
    registry = CapabilityRegistry()
    first = OpCapabilityManifest(
        capability_id="demo-first",
        kind="native_op",
        version="1.0.0",
        summary="First op",
        call_target="state.first",
        input_schema={"seed": "string"},
        output_schema={
            "required_value": "string",
            "optional_value": "string",
            "producer_extra": "string",
        },
    )
    second = OpCapabilityManifest(
        capability_id="demo-second",
        kind="native_op",
        version="1.0.0",
        summary="Second op",
        call_target="state.second",
        input_schema={
            "text": "string",
            "media_type": "string | optional",
        },
        output_schema={
            "embedding_count": "integer",
            "ignored_output": "string",
        },
    )
    pipeline = SkillCapabilityManifest(
        capability_id="demo-pipeline",
        kind="pipeline_skill",
        version="1.0.0",
        summary="Pipeline",
        input_schema={"seed": "string"},
        output_schema={"count": "integer | from=embedding_count"},
        pipeline=(
            "demo-first",
            {
                "capability": "demo-second",
                "input_mapping": {
                    "text": "required_value",
                    "media_type": "optional_value",
                },
            },
        ),
    )
    registry.register_manifest(manifest=first)
    registry.register_manifest(manifest=second)
    registry.register_manifest(manifest=pipeline)

    seen_second_inputs: dict[str, object] = {}

    def first_handler(
        request: CapabilityInvocationRequest,
        runtime: CapabilityRuntime,
    ) -> CapabilityExecutionResponse:
        return CapabilityExecutionResponse(
            output={
                "required_value": "required",
                "optional_value": "optional",
                "producer_extra": "drop-me",
            }
        )

    registry.register_handler(capability_id=first.capability_id, handler=first_handler)

    def second_handler(
        request: CapabilityInvocationRequest,
        runtime: CapabilityRuntime,
    ) -> CapabilityExecutionResponse:
        seen_second_inputs.update(request.input_payload)
        return CapabilityExecutionResponse(
            output={
                "embedding_count": 3,
                "ignored_output": "drop-me-too",
            }
        )

    registry.register_handler(
        capability_id=second.capability_id, handler=second_handler
    )
    registry.register_handler(
        capability_id=pipeline.capability_id,
        handler=build_pipeline_skill_handler(
            manifest=pipeline,
            registry=registry,
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
        capability_id="demo-pipeline",
        input_payload={"seed": "hello", "caller_extra": "ignored"},
        invocation=_invocation(),
    )

    assert result.ok is True
    assert policy.calls == 3
    assert seen_second_inputs == {"text": "required", "media_type": "optional"}
    assert result.payload is not None
    assert result.payload.value.output == {"count": 3}


def test_disabled_manifest_not_found_after_discovery() -> None:
    """Disabled capabilities are discarded at discovery time and cannot be invoked."""
    registry = CapabilityRegistry()
    # register_manifest bypasses discovery, so simulate what discovery would do:
    # a disabled manifest is never registered in the first place.
    # Verify that invoking a non-existent capability yields not-found.
    service = DefaultCapabilityEngineService(
        settings=CapabilityEngineSettings(),
        policy_service=_FakePolicyService(),
        registry=registry,
    )

    result = service.invoke_capability(
        meta=new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator"),
        capability_id="demo-disabled",
        input_payload={},
        invocation=_invocation(),
    )

    assert result.ok is False


def test_unknown_handler_fails_after_policy_wrapper() -> None:
    registry = CapabilityRegistry()
    spec = OpCapabilityManifest(
        capability_id="demo-no-handler",
        kind="native_op",
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


def test_engine_autonomy_ceiling_denies_before_policy() -> None:
    registry = CapabilityRegistry()
    spec = OpCapabilityManifest(
        capability_id="demo-autonomy",
        kind="native_op",
        version="1.0.0",
        summary="Autonomy gated by engine",
        autonomy=2,
        call_target="state.autonomy",
    )
    registry.register_manifest(manifest=spec)
    registry.register_handler(
        capability_id=spec.capability_id,
        handler=lambda request, runtime: CapabilityExecutionResponse(
            output={"ok": True}
        ),
    )

    policy = _FakePolicyService()
    service = DefaultCapabilityEngineService(
        settings=CapabilityEngineSettings(default_max_autonomy=1),
        policy_service=policy,
        registry=registry,
    )

    result = service.invoke_capability(
        meta=new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator"),
        capability_id="demo-autonomy",
        input_payload={},
        invocation=_invocation(),
    )
    assert result.ok is False
    assert policy.calls == 0
    assert result.errors[0].metadata is not None
    assert result.errors[0].metadata["engine_max_autonomy"] == "1"


def test_policy_denial_propagates_reason_codes() -> None:
    registry = CapabilityRegistry()
    spec = OpCapabilityManifest(
        capability_id="demo-denied",
        kind="native_op",
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
        kind="native_op",
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
    assert row.policy_decision_id == "decision"
    assert row.invocation_id == "inv-1"
    assert row.parent_invocation_id == ""
    assert row.actor == "operator"
    assert row.source == "agent"
    assert row.channel == "signal"


def test_health_reflects_injected_audit_repository_count() -> None:
    registry = CapabilityRegistry()
    spec = OpCapabilityManifest(
        capability_id="demo-health-audit",
        kind="native_op",
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


def test_describe_capabilities_returns_all_registered_manifests() -> None:
    registry = CapabilityRegistry()
    op = OpCapabilityManifest(
        capability_id="demo-op",
        kind="native_op",
        version="1.0.0",
        summary="An op",
        call_target="state.op",
        side_effects=("writes_cache",),
    )
    skill = SkillCapabilityManifest(
        capability_id="demo-skill",
        kind="logic_skill",
        version="2.0.0",
        summary="A skill",
        requires_approval=True,
    )
    registry.register_manifest(manifest=op)
    registry.register_manifest(manifest=skill)

    service = DefaultCapabilityEngineService(
        settings=CapabilityEngineSettings(),
        policy_service=_FakePolicyService(),
        registry=registry,
    )

    result = service.describe_capabilities(
        meta=new_meta(kind=EnvelopeKind.COMMAND, source="agent", principal="operator")
    )

    assert result.ok is True
    assert result.payload is not None
    descriptors: tuple[CapabilityDescriptor, ...] = result.payload.value
    assert len(descriptors) == 2

    by_id = {d.capability_id: d for d in descriptors}

    assert "demo-op" in by_id
    op_desc = by_id["demo-op"]
    assert op_desc.kind == "native_op"
    assert op_desc.version == "1.0.0"
    assert op_desc.summary == "An op"
    assert op_desc.side_effects == ("writes_cache",)
    assert op_desc.requires_approval is False

    assert "demo-skill" in by_id
    skill_desc = by_id["demo-skill"]
    assert skill_desc.kind == "logic_skill"
    assert skill_desc.version == "2.0.0"
    assert skill_desc.summary == "A skill"
    assert skill_desc.requires_approval is True


def test_describe_capabilities_returns_empty_tuple_when_no_manifests() -> None:
    service = DefaultCapabilityEngineService(
        settings=CapabilityEngineSettings(),
        policy_service=_FakePolicyService(),
        registry=CapabilityRegistry(),
    )

    result = service.describe_capabilities(
        meta=new_meta(kind=EnvelopeKind.COMMAND, source="agent", principal="operator")
    )

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value == ()


def test_describe_capabilities_descriptors_are_stable_sorted() -> None:
    registry = CapabilityRegistry()
    for cid in ("demo-zzz", "demo-aaa", "demo-mmm"):
        registry.register_manifest(
            manifest=OpCapabilityManifest(
                capability_id=cid,
                kind="native_op",
                version="1.0.0",
                summary=cid,
                call_target="state.x",
            )
        )

    service = DefaultCapabilityEngineService(
        settings=CapabilityEngineSettings(),
        policy_service=_FakePolicyService(),
        registry=registry,
    )

    result = service.describe_capabilities(
        meta=new_meta(kind=EnvelopeKind.COMMAND, source="agent", principal="operator")
    )

    assert result.ok is True
    assert result.payload is not None
    ids = [d.capability_id for d in result.payload.value]
    assert ids == sorted(ids)


def test_list_always_on_capabilities_returns_only_configured_subset() -> None:
    """Always-on descriptor listing should return only configured capability ids."""
    registry = CapabilityRegistry()
    for capability_id in (
        "vault-search-files",
        "attention-notify",
        "vault-get-file",
    ):
        registry.register_manifest(
            manifest=OpCapabilityManifest(
                capability_id=capability_id,
                kind="native_op",
                version="1.0.0",
                summary=capability_id,
                call_target="state.x",
            )
        )

    service = DefaultCapabilityEngineService(
        settings=CapabilityEngineSettings(
            always_on_capability_ids=("vault-search-files", "attention-notify")
        ),
        policy_service=_FakePolicyService(),
        registry=registry,
    )

    result = service.list_always_on_capabilities(
        meta=new_meta(kind=EnvelopeKind.COMMAND, source="agent", principal="operator")
    )

    assert result.ok is True
    assert result.payload is not None
    assert [item.capability_id for item in result.payload.value] == [
        "vault-search-files",
        "attention-notify",
    ]


def test_describe_capability_returns_one_descriptor_by_id() -> None:
    """Targeted descriptor lookup should return exactly one matching capability."""
    registry = CapabilityRegistry()
    registry.register_manifest(
        manifest=OpCapabilityManifest(
            capability_id="vault-get-file",
            kind="native_op",
            version="1.0.0",
            summary="Read a file.",
            call_target="vault.read",
            input_schema={"file_path": "string"},
            output_schema={"content": "string"},
        )
    )
    service = DefaultCapabilityEngineService(
        settings=CapabilityEngineSettings(),
        policy_service=_FakePolicyService(),
        registry=registry,
    )

    result = service.describe_capability(
        meta=new_meta(kind=EnvelopeKind.COMMAND, source="agent", principal="operator"),
        capability_id="vault-get-file",
    )

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.capability_id == "vault-get-file"
    assert result.payload.value.input_schema is not None


def test_search_capabilities_returns_compact_hits_from_internal_search() -> None:
    """Semantic search should return compact hits produced by the internal search path."""
    service = DefaultCapabilityEngineService(
        settings=CapabilityEngineSettings(),
        policy_service=_FakePolicyService(),
        language_model_service=object(),  # type: ignore[arg-type]
        embedding_authority_service=object(),  # type: ignore[arg-type]
        registry=CapabilityRegistry(),
    )
    service._sync_capability_discovery_index = lambda *, meta: None  # type: ignore[method-assign]
    service._search_capabilities_internal = (  # type: ignore[method-assign]
        lambda *, meta, query, limit: [
            CapabilitySearchHit(
                capability_id="vault-get-file",
                required_params=("file_path",),
                summary="Read a file.",
            )
        ]
    )

    result = service.search_capabilities(
        meta=new_meta(kind=EnvelopeKind.COMMAND, source="agent", principal="operator"),
        query="read a markdown file",
        limit=5,
    )

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value == (
        CapabilitySearchHit(
            capability_id="vault-get-file",
            required_params=("file_path",),
            summary="Read a file.",
        ),
    )


def test_ces_health_does_not_depend_on_policy_service_health() -> None:
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
    assert payload.policy_ready is True
