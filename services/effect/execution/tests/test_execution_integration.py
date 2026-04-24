"""Integration-style Execution tests across registry/policy/audit boundaries."""

from __future__ import annotations

import json
from pathlib import Path

from lib.shared.envelope import EnvelopeKind, new_meta
from services.effect.execution.config import ExecutionSettings
from services.effect.execution.data.repository import (
    InMemoryOpInvocationAuditRepository,
)
from services.effect.execution.domain import (
    OpExecutionResponse,
    OpInvocationMetadata,
)
from services.effect.execution.implementation import (
    DefaultExecutionService,
)
from services.effect.execution.registry import (
    CallTargetContract,
    OpRegistry,
)


def _write_manifest(root: Path) -> None:
    """Write one valid op package for invocation tests."""
    pkg = root / "demo-echo"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "README.md").write_text("# demo", encoding="utf-8")
    (pkg / "op.json").write_text(
        json.dumps(
            {
                "op_id": "demo-echo",
                "kind": "native",
                "version": "1.0.0",
                "summary": "Echo",
                "effect": "read",
                "approval": "never",
                "input_schema": {"payload": "object | The payload to echo."},
                "output_schema": "object | The echoed payload.",
                "call_target": "state.echo",
            }
        ),
        encoding="utf-8",
    )


class _AllowPolicy:
    """Policy fake that allows execution callback path."""

    def authorize_and_execute(self, *, request, execute):
        return execute(request)

    def health(self, *, meta):
        from lib.shared.envelope import success
        from services.reason.policy.domain import PolicyHealthStatus

        return success(
            meta=meta,
            payload=PolicyHealthStatus(
                service_ready=True,
                active_policy_regime_id="r",
                regime_rows=1,
                decision_log_rows=0,
                proposal_rows=0,
                dedupe_rows=0,
                detail="ok",
            ),
        )


def _meta():
    """Build deterministic metadata for invoke requests."""
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def test_invoke_writes_audit_for_allowed_call(tmp_path: Path) -> None:
    """Allowed op invokes should append one audit row."""
    discovery = tmp_path / "caps"
    _write_manifest(discovery)
    registry = OpRegistry()
    registry.discover(
        roots=(discovery,),
        call_targets={
            "state.echo": CallTargetContract(
                input_schema={
                    "type": "object",
                    "properties": {"payload": {"type": "object"}},
                    "required": ["payload"],
                    "additionalProperties": False,
                },
                output_schema={"type": "object"},
            )
        },
    )
    registry.register_handler(
        op_id="demo-echo",
        handler=lambda _request, _runtime: OpExecutionResponse(output={"ok": True}),
    )
    audit = InMemoryOpInvocationAuditRepository()
    service = DefaultExecutionService(
        settings=ExecutionSettings(discovery_roots=(str(discovery),)),
        policy_service=_AllowPolicy(),
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
