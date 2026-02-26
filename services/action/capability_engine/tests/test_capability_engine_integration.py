"""Integration-style Capability Engine tests across registry/policy/audit boundaries."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.brain_shared.envelope import EnvelopeKind, new_meta
from resources.adapters.utcp_code_mode import UtcpCodeModeConfigNotFoundError
from services.action.capability_engine.config import CapabilityEngineSettings
from services.action.capability_engine.data.repository import (
    InMemoryCapabilityInvocationAuditRepository,
)
from services.action.capability_engine.domain import (
    CapabilityExecutionResponse,
    CapabilityInvocationMetadata,
)
from services.action.capability_engine.implementation import (
    DefaultCapabilityEngineService,
)
from services.action.capability_engine.registry import (
    CallTargetContract,
    CapabilityRegistry,
)


def _write_manifest(root: Path) -> None:
    """Write one valid capability package for invocation tests."""
    pkg = root / "demo-echo"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "README.md").write_text("# demo", encoding="utf-8")
    (pkg / "capability.json").write_text(
        json.dumps(
            {
                "capability_id": "demo-echo",
                "kind": "op",
                "version": "1.0.0",
                "summary": "Echo",
                "input_types": ["dict[str, object]"],
                "output_types": ["dict[str, object]"],
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
        from packages.brain_shared.envelope import success
        from services.action.policy_service.domain import PolicyHealthStatus

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


def test_from_settings_fails_when_utcp_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """CES from_settings should hard-fail when UTCP YAML path is missing."""
    from packages.brain_shared.config import BrainSettings

    monkeypatch.setattr(
        "services.action.capability_engine.implementation.CapabilityEnginePostgresRuntime.from_settings",
        lambda _settings: type("_R", (), {"schema_sessions": object()})(),
    )
    settings = BrainSettings(
        components={
            "service": {
                "capability_engine": {"discovery_root": str(tmp_path / "caps")}
            },
            "adapter": {
                "utcp_code_mode": {
                    "utcp_yaml_config_path": str(tmp_path / "missing.yaml"),
                    "generated_utcp_json_path": str(tmp_path / "generated.json"),
                }
            },
        }
    )
    with pytest.raises(UtcpCodeModeConfigNotFoundError):
        DefaultCapabilityEngineService.from_settings(
            settings, policy_service=_AllowPolicy()
        )


def test_invoke_writes_audit_for_allowed_call(tmp_path: Path) -> None:
    """Allowed capability invokes should append one audit row."""
    discovery = tmp_path / "caps"
    _write_manifest(discovery)
    registry = CapabilityRegistry()
    registry.discover(
        root=discovery,
        call_targets={
            "state.echo": CallTargetContract(
                input_types=("dict[str, object]",),
                output_types=("dict[str, object]",),
            )
        },
    )
    registry.register_handler(
        capability_id="demo-echo",
        handler=lambda _request, _runtime: CapabilityExecutionResponse(
            output={"ok": True}
        ),
    )
    audit = InMemoryCapabilityInvocationAuditRepository()
    service = DefaultCapabilityEngineService(
        settings=CapabilityEngineSettings(discovery_root=str(discovery)),
        policy_service=_AllowPolicy(),
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
