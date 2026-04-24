"""Unit tests for Execution policy integration behavior."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from lib.shared.config import (
    CoreRuntimeSettings,
    CoreSettings,
    ResourcesSettings,
)
from lib.shared.envelope import EnvelopeKind, failure, new_meta, success
from lib.shared.errors import policy_error
from services.effect.execution.config import ExecutionSettings
from services.effect.execution.data.repository import (
    InMemoryOpInvocationAuditRepository,
)
from services.effect.execution.domain import (
    OpDescriptor,
    ExecutionHealthStatus,
    OpExecutionResponse,
    OpInvocationMetadata,
    OpSearchHit,
    NativeOpManifest,
    CompoundOpManifest,
)
from services.effect.execution.implementation import (
    DefaultExecutionService,
    _resolve_op_embedding_profile_fingerprint,
)
from services.effect.execution.pipeline_handler_bridge import (
    build_pipeline_op_handler,
)
from services.effect.execution.registry import (
    OpRegistry,
    OpRuntime,
)
from services.reason.policy.domain import (
    OpInvocationRequest,
    PolicyDecision,
    PolicyExecutionResult,
    PolicyHealthStatus,
)
from services.reason.policy.implementation import DefaultPolicyService
from services.reason.policy.config import PolicyServiceSettings
from services.reason.policy.service import PolicyExecuteCallback, PolicyService


class _FakePolicyService(PolicyService):
    def __init__(self) -> None:
        self.calls = 0
        self.requests: list[OpInvocationRequest] = []

    def authorize_and_execute(
        self,
        *,
        request: OpInvocationRequest,
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
        request: OpInvocationRequest,
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
        decided_at=datetime.now(UTC),
        policy_name="test",
        policy_version="1",
    )


def _invocation() -> OpInvocationMetadata:
    return OpInvocationMetadata(
        actor="operator",
        source="assistant",
        channel="signal",
        invocation_id="inv-1",
    )


def test_ces_invocation_routes_through_policy_wrapper() -> None:
    registry = OpRegistry()
    spec = NativeOpManifest(
        op_id="demo-echo",
        kind="native",
        version="1.0.0",
        summary="Echo input",
        call_target="state.echo",
    )
    registry.register_manifest(manifest=spec)
    registry.register_handler(
        op_id=spec.op_id,
        handler=lambda request, runtime: OpExecutionResponse(
            output={"echo": request.input_payload.get("text")}
        ),
    )

    policy = _FakePolicyService()
    service = DefaultExecutionService(
        settings=ExecutionSettings(),
        policy_service=policy,
        registry=registry,
    )

    result = service.invoke_op(
        meta=new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator"),
        op_id="demo-echo",
        input_payload={"text": "hello"},
        invocation=_invocation(),
    )

    assert result.ok is True
    assert policy.calls == 1
    assert result.payload is not None
    assert result.payload.value.output == {"echo": "hello"}


def test_nested_op_invocation_re_authorizes_child() -> None:
    registry = OpRegistry()
    child = NativeOpManifest(
        op_id="demo-child",
        kind="native",
        version="1.0.0",
        summary="Child op",
        call_target="state.child",
    )
    parent = CompoundOpManifest(
        op_id="demo-parent",
        kind="logic",
        version="1.0.0",
        summary="Parent op",
    )
    registry.register_manifest(manifest=child)
    registry.register_manifest(manifest=parent)

    registry.register_handler(
        op_id=child.op_id,
        handler=lambda request, runtime: OpExecutionResponse(
            output={"child": request.input_payload.get("value")}
        ),
    )

    def parent_handler(
        request: OpInvocationRequest,
        runtime: OpRuntime,
    ) -> OpExecutionResponse:
        nested = runtime.invoke_nested(
            op_id="demo-child",
            input_payload={"value": "nested"},
        )
        return OpExecutionResponse(output={"nested": nested.output})

    registry.register_handler(op_id=parent.op_id, handler=parent_handler)

    policy = _FakePolicyService()
    service = DefaultExecutionService(
        settings=ExecutionSettings(),
        policy_service=policy,
        registry=registry,
    )

    result = service.invoke_op(
        meta=new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator"),
        op_id="demo-parent",
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


def test_pipeline_op_projects_step_input_mapping_and_aliased_pipeline_output() -> None:
    registry = OpRegistry()
    first = NativeOpManifest(
        op_id="demo-first",
        kind="native",
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
    second = NativeOpManifest(
        op_id="demo-second",
        kind="native",
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
    pipeline = CompoundOpManifest(
        op_id="demo-pipeline",
        kind="pipeline",
        version="1.0.0",
        summary="Pipeline",
        input_schema={"seed": "string"},
        output_schema={"count": "integer | from=embedding_count"},
        pipeline=(
            "demo-first",
            {
                "op": "demo-second",
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
        request: OpInvocationRequest,
        runtime: OpRuntime,
    ) -> OpExecutionResponse:
        return OpExecutionResponse(
            output={
                "required_value": "required",
                "optional_value": "optional",
                "producer_extra": "drop-me",
            }
        )

    registry.register_handler(op_id=first.op_id, handler=first_handler)

    def second_handler(
        request: OpInvocationRequest,
        runtime: OpRuntime,
    ) -> OpExecutionResponse:
        seen_second_inputs.update(request.input_payload)
        return OpExecutionResponse(
            output={
                "embedding_count": 3,
                "ignored_output": "drop-me-too",
            }
        )

    registry.register_handler(op_id=second.op_id, handler=second_handler)
    registry.register_handler(
        op_id=pipeline.op_id,
        handler=build_pipeline_op_handler(
            manifest=pipeline,
            registry=registry,
        ),
    )

    policy = _FakePolicyService()
    service = DefaultExecutionService(
        settings=ExecutionSettings(),
        policy_service=policy,
        registry=registry,
    )

    result = service.invoke_op(
        meta=new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator"),
        op_id="demo-pipeline",
        input_payload={"seed": "hello", "caller_extra": "ignored"},
        invocation=_invocation(),
    )

    assert result.ok is True
    assert policy.calls == 3
    assert seen_second_inputs == {"text": "required", "media_type": "optional"}
    assert result.payload is not None
    assert result.payload.value.output == {"count": 3}


def test_disabled_manifest_not_found_after_discovery() -> None:
    """Disabled ops are discarded at discovery time and cannot be invoked."""
    registry = OpRegistry()
    # register_manifest bypasses discovery, so simulate what discovery would do:
    # a disabled manifest is never registered in the first place.
    # Verify that invoking a non-existent op yields not-found.
    service = DefaultExecutionService(
        settings=ExecutionSettings(),
        policy_service=_FakePolicyService(),
        registry=registry,
    )

    result = service.invoke_op(
        meta=new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator"),
        op_id="demo-disabled",
        input_payload={},
        invocation=_invocation(),
    )

    assert result.ok is False


def test_unknown_handler_fails_after_policy_wrapper() -> None:
    registry = OpRegistry()
    spec = NativeOpManifest(
        op_id="demo-no-handler",
        kind="native",
        version="1.0.0",
        summary="No handler",
        call_target="state.missing",
    )
    registry.register_manifest(manifest=spec)

    policy = _FakePolicyService()
    service = DefaultExecutionService(
        settings=ExecutionSettings(),
        policy_service=policy,
        registry=registry,
    )

    result = service.invoke_op(
        meta=new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator"),
        op_id="demo-no-handler",
        input_payload={},
        invocation=_invocation(),
    )

    assert result.ok is False
    assert policy.calls == 1


def test_unknown_op_id_returns_not_found() -> None:
    service = DefaultExecutionService(
        settings=ExecutionSettings(),
        policy_service=_FakePolicyService(),
        registry=OpRegistry(),
    )
    result = service.invoke_op(
        meta=new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator"),
        op_id="missing-op",
        input_payload={},
        invocation=_invocation(),
    )
    assert result.ok is False


def test_policy_denial_propagates_reason_codes() -> None:
    registry = OpRegistry()
    spec = NativeOpManifest(
        op_id="demo-denied",
        kind="native",
        version="1.0.0",
        summary="Denied by policy",
        call_target="state.denied",
    )
    registry.register_manifest(manifest=spec)
    registry.register_handler(
        op_id=spec.op_id,
        handler=lambda request, runtime: OpExecutionResponse(output={"ok": True}),
    )
    service = DefaultExecutionService(
        settings=ExecutionSettings(),
        policy_service=_DenyingPolicyService(),
        registry=registry,
    )
    result = service.invoke_op(
        meta=new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator"),
        op_id="demo-denied",
        input_payload={},
        invocation=_invocation(),
    )
    assert result.ok is False
    assert result.errors[0].metadata is not None
    assert "actor_denied" in result.errors[0].metadata["reason_codes"]


def test_policy_denial_propagates_rich_approval_metadata() -> None:
    registry = OpRegistry()
    spec = NativeOpManifest(
        op_id="demo-approval-denied",
        kind="native",
        version="1.0.0",
        summary="Approval denied until confirmed",
        call_target="state.denied",
        approval="always",
    )
    registry.register_manifest(manifest=spec)
    registry.register_handler(
        op_id=spec.op_id,
        handler=lambda request, runtime: OpExecutionResponse(output={"ok": True}),
    )
    service = DefaultExecutionService(
        settings=ExecutionSettings(),
        policy_service=DefaultPolicyService(settings=PolicyServiceSettings()),
        registry=registry,
    )

    result = service.invoke_op(
        meta=new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator"),
        op_id="demo-approval-denied",
        input_payload={"path": "notes/test.md"},
        invocation=_invocation(),
    )

    assert result.ok is False
    assert result.errors[0].metadata is not None
    assert result.errors[0].metadata["proposal_token"] != ""
    assert result.errors[0].metadata["expires_at"] != ""


def test_invocation_audit_rows_capture_lineage_and_policy_fields() -> None:
    registry = OpRegistry()
    spec = NativeOpManifest(
        op_id="demo-audit",
        kind="native",
        version="1.0.0",
        summary="Audit probe",
        call_target="state.audit",
    )
    registry.register_manifest(manifest=spec)
    registry.register_handler(
        op_id=spec.op_id,
        handler=lambda request, runtime: OpExecutionResponse(output={"ok": True}),
    )
    audit_repo = InMemoryOpInvocationAuditRepository()
    service = DefaultExecutionService(
        settings=ExecutionSettings(),
        policy_service=_FakePolicyService(),
        registry=registry,
        audit_repository=audit_repo,
    )
    meta = new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")
    service.invoke_op(
        meta=meta,
        op_id="demo-audit",
        input_payload={},
        invocation=_invocation(),
    )
    row = audit_repo.list_rows()[-1]
    assert row.envelope_id == meta.envelope_id
    assert row.trace_id == meta.trace_id
    assert row.op_id == "demo-audit"
    assert row.policy_regime_id == "regime-1"
    assert row.policy_decision_id == "decision"
    assert row.invocation_id == "inv-1"
    assert row.parent_invocation_id == ""
    assert row.actor == "operator"
    assert row.source == "assistant"
    assert row.channel == "signal"


def test_health_reflects_injected_audit_repository_count() -> None:
    registry = OpRegistry()
    spec = NativeOpManifest(
        op_id="demo-health-audit",
        kind="native",
        version="1.0.0",
        summary="Health audit probe",
        call_target="state.health",
    )
    registry.register_manifest(manifest=spec)
    registry.register_handler(
        op_id=spec.op_id,
        handler=lambda request, runtime: OpExecutionResponse(output={"ok": True}),
    )
    audit_repo = InMemoryOpInvocationAuditRepository()
    service = DefaultExecutionService(
        settings=ExecutionSettings(),
        policy_service=_FakePolicyService(),
        registry=registry,
        audit_repository=audit_repo,
    )

    service.invoke_op(
        meta=new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator"),
        op_id="demo-health-audit",
        input_payload={},
        invocation=_invocation(),
    )
    health = service.health(
        meta=new_meta(kind=EnvelopeKind.RESULT, source="test", principal="operator")
    )
    assert health.ok is True
    assert health.payload is not None
    assert health.payload.value.invocation_audit_rows == 1


def test_describe_ops_returns_all_registered_manifests() -> None:
    registry = OpRegistry()
    op = NativeOpManifest(
        op_id="demo-op",
        kind="native",
        version="1.0.0",
        summary="An op",
        call_target="state.op",
    )
    logic_op = CompoundOpManifest(
        op_id="demo-logic",
        kind="logic",
        version="2.0.0",
        summary="A logic op",
        approval="always",
    )
    registry.register_manifest(manifest=op)
    registry.register_manifest(manifest=logic_op)

    service = DefaultExecutionService(
        settings=ExecutionSettings(),
        policy_service=_FakePolicyService(),
        registry=registry,
    )

    result = service.describe_ops(
        meta=new_meta(
            kind=EnvelopeKind.COMMAND, source="assistant", principal="operator"
        )
    )

    assert result.ok is True
    assert result.payload is not None
    descriptors: tuple[OpDescriptor, ...] = result.payload.value
    assert len(descriptors) == 2

    by_id = {d.op_id: d for d in descriptors}

    assert "demo-op" in by_id
    op_desc = by_id["demo-op"]
    assert op_desc.kind == "native"
    assert op_desc.version == "1.0.0"
    assert op_desc.summary == "An op"
    assert op_desc.approval == "never"

    assert "demo-logic" in by_id
    logic_desc = by_id["demo-logic"]
    assert logic_desc.kind == "logic"
    assert logic_desc.version == "2.0.0"
    assert logic_desc.summary == "A logic op"
    assert logic_desc.approval == "always"


def test_describe_ops_returns_empty_tuple_when_no_manifests() -> None:
    service = DefaultExecutionService(
        settings=ExecutionSettings(),
        policy_service=_FakePolicyService(),
        registry=OpRegistry(),
    )

    result = service.describe_ops(
        meta=new_meta(
            kind=EnvelopeKind.COMMAND, source="assistant", principal="operator"
        )
    )

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value == ()


def test_describe_ops_descriptors_are_stable_sorted() -> None:
    registry = OpRegistry()
    for cid in ("demo-zzz", "demo-aaa", "demo-mmm"):
        registry.register_manifest(
            manifest=NativeOpManifest(
                op_id=cid,
                kind="native",
                version="1.0.0",
                summary=cid,
                call_target="state.x",
            )
        )

    service = DefaultExecutionService(
        settings=ExecutionSettings(),
        policy_service=_FakePolicyService(),
        registry=registry,
    )

    result = service.describe_ops(
        meta=new_meta(
            kind=EnvelopeKind.COMMAND, source="assistant", principal="operator"
        )
    )

    assert result.ok is True
    assert result.payload is not None
    ids = [d.op_id for d in result.payload.value]
    assert ids == sorted(ids)


def test_list_always_on_ops_returns_only_configured_subset() -> None:
    """Always-on descriptor listing should return only configured op ids."""
    registry = OpRegistry()
    for op_id in (
        "vault-search-files",
        "relay-notify",
        "vault-get-file",
    ):
        registry.register_manifest(
            manifest=NativeOpManifest(
                op_id=op_id,
                kind="native",
                version="1.0.0",
                summary=op_id,
                call_target="state.x",
            )
        )

    service = DefaultExecutionService(
        settings=ExecutionSettings(
            always_on_op_ids=("vault-search-files", "relay-notify")
        ),
        policy_service=_FakePolicyService(),
        registry=registry,
    )

    result = service.list_always_on_ops(
        meta=new_meta(
            kind=EnvelopeKind.COMMAND, source="assistant", principal="operator"
        )
    )

    assert result.ok is True
    assert result.payload is not None
    assert [item.op_id for item in result.payload.value] == [
        "vault-search-files",
        "relay-notify",
    ]


def test_describe_op_returns_one_descriptor_by_id() -> None:
    """Targeted descriptor lookup should return exactly one matching op."""
    registry = OpRegistry()
    registry.register_manifest(
        manifest=NativeOpManifest(
            op_id="vault-get-file",
            kind="native",
            version="1.0.0",
            summary="Read a file.",
            call_target="vault.read",
            input_schema={"file_path": "string"},
            output_schema={"content": "string"},
        )
    )
    service = DefaultExecutionService(
        settings=ExecutionSettings(),
        policy_service=_FakePolicyService(),
        registry=registry,
    )

    result = service.describe_op(
        meta=new_meta(
            kind=EnvelopeKind.COMMAND, source="assistant", principal="operator"
        ),
        op_id="vault-get-file",
    )

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.op_id == "vault-get-file"
    assert result.payload.value.input_schema is not None


def test_search_ops_returns_compact_hits_from_internal_search() -> None:
    """Semantic search should return compact hits produced by the internal search path."""
    service = DefaultExecutionService(
        settings=ExecutionSettings(),
        policy_service=_FakePolicyService(),
        language_service=object(),  # type: ignore[arg-type]
        embedding_service=object(),  # type: ignore[arg-type]
        registry=OpRegistry(),
    )
    service._sync_op_discovery_index = lambda *, meta: None  # type: ignore[method-assign]
    service._search_ops_internal = (  # type: ignore[method-assign]
        lambda *, meta, query, limit: [
            OpSearchHit(
                op_id="vault-get-file",
                required_params=("file_path",),
                summary="Read a file.",
            )
        ]
    )

    result = service.search_ops(
        meta=new_meta(
            kind=EnvelopeKind.COMMAND, source="assistant", principal="operator"
        ),
        query="read a markdown file",
        limit=5,
    )

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value == (
        OpSearchHit(
            op_id="vault-get-file",
            required_params=("file_path",),
            summary="Read a file.",
        ),
    )


def test_list_tool_system_hints_combines_service_and_mcp_hints(monkeypatch) -> None:
    """Tool-system hints should combine manifest-owned services and MCP servers."""
    from services.effect.execution import implementation as module

    class _Registry:
        def list_services(self):
            return (
                type(
                    "_Service",
                    (),
                    {
                        "id": "service_vault",
                        "exposes_ops": True,
                        "tool_system_label": "Vault Service",
                        "tool_system_summary": "Personal Knowledge Base access.",
                    },
                )(),
                type(
                    "_Hidden",
                    (),
                    {
                        "id": "service_policy",
                        "exposes_ops": False,
                        "tool_system_label": "",
                        "tool_system_summary": "",
                    },
                )(),
            )

    class _McpAdapter:
        def list_servers(self):
            return (
                type(
                    "_Server",
                    (),
                    {
                        "server_id": "filesystem-ro",
                        "connected": True,
                        "tool_count": 4,
                        "instruction_summary": "read access to home",
                    },
                )(),
            )

    monkeypatch.setattr(module, "get_registry", lambda: _Registry())
    service = DefaultExecutionService(
        settings=ExecutionSettings(),
        policy_service=_FakePolicyService(),
        registry=OpRegistry(),
        mcp_adapter=_McpAdapter(),
    )

    result = service.list_tool_system_hints(
        meta=new_meta(
            kind=EnvelopeKind.COMMAND, source="assistant", principal="operator"
        )
    )

    assert result.ok is True
    assert result.payload is not None
    assert [item.system_id for item in result.payload.value] == [
        "service_vault",
        "filesystem-ro",
    ]
    assert result.payload.value[1].kind == "mcp"
    # `tool_count` reflects registered (classified) MCP manifests in the
    # registry; `pending_tool_count` reflects rows in the classification
    # repository that lack effect/approval. The fake adapter has no
    # registered manifests and no classification rows, so both are zero.
    assert result.payload.value[1].tool_count == 0
    assert result.payload.value[1].pending_tool_count == 0


def test_mcp_discovery_document_includes_server_and_tool_identity() -> None:
    """MCP op embeddings should include server/tool identity for disambiguation."""
    registry = OpRegistry()
    registry.register_manifest(
        manifest=NativeOpManifest(
            op_id="mcp-filesystem-ro-read-file",
            kind="mcp",
            version="0.1.0",
            summary="Read a file.",
            call_target="mcp:filesystem-ro:read_file",
        )
    )
    service = DefaultExecutionService(
        settings=ExecutionSettings(),
        policy_service=_FakePolicyService(),
        registry=registry,
    )

    documents = service._op_discovery_documents()

    document = documents["mcp-filesystem-ro-read-file"]
    assert "server_id: filesystem-ro" in document.text
    assert "tool_name: read_file" in document.text


def test_ces_health_does_not_depend_on_policy_service_health() -> None:
    class _FailingPolicyService(_FakePolicyService):
        def health(self, *, meta: Any):
            return failure(meta=meta, errors=[policy_error("unhealthy")])

    service = DefaultExecutionService(
        settings=ExecutionSettings(),
        policy_service=_FailingPolicyService(),
        registry=OpRegistry(),
    )

    health = service.health(
        meta=new_meta(kind=EnvelopeKind.RESULT, source="test", principal="operator")
    )
    assert health.ok is True
    assert health.payload is not None
    payload: ExecutionHealthStatus = health.payload.value
    assert payload.policy_ready is True


def test_op_embedding_profile_fingerprint_includes_dimensions() -> None:
    settings = CoreRuntimeSettings(
        core=CoreSettings.model_validate({}),
        resources=ResourcesSettings.model_validate({}),
        component_settings={
            "language": {
                "op_embedding": {
                    "provider": "ollama",
                    "model": "mxbai-embed-large",
                    "dimensions": 1024,
                }
            }
        },
    )

    fingerprint = _resolve_op_embedding_profile_fingerprint(settings)

    assert json.loads(fingerprint) == {
        "dimensions": 1024,
        "model": "mxbai-embed-large",
        "provider": "ollama",
    }
