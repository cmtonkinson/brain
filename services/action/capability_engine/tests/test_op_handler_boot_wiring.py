"""Unit tests for boot-time auto-registration of Op handlers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lib.shared.config import (
    CoreRuntimeSettings,
    CoreSettings,
    ResourcesSettings,
)
from lib.shared.envelope import EnvelopeMeta
from lib.shared.envelope.envelope import Envelope
from lib.shared.envelope.payload import Payload
from services.action.capability_engine.component import after_boot
from services.action.capability_engine.config import CapabilityEngineSettings
from services.action.capability_engine.domain import CapabilityExecutionResponse
from services.action.capability_engine.implementation import (
    DefaultCapabilityEngineService,
)
from services.action.capability_engine.registry import CapabilityRegistry
from services.action.policy_service.domain import (
    CapabilityInvocationRequest,
    PolicyDecision,
    PolicyExecutionResult,
    PolicyHealthStatus,
    utc_now,
)
from services.action.policy_service.service import PolicyExecuteCallback, PolicyService


def _settings() -> CoreRuntimeSettings:
    return CoreRuntimeSettings(
        core=CoreSettings(),
        resources=ResourcesSettings(),
    )


class _FakePolicyService(PolicyService):
    def authorize_and_execute(
        self,
        *,
        request: CapabilityInvocationRequest,
        execute: PolicyExecuteCallback,
    ) -> PolicyExecutionResult:
        callback = execute(request)
        return callback.model_copy(
            update={
                "decision": PolicyDecision(
                    decision_id="d",
                    policy_regime_id="r",
                    policy_regime_hash="h",
                    allowed=True,
                    reason_codes=(),
                    obligations=(),
                    policy_metadata={},
                    decided_at=utc_now(),
                    policy_name="test",
                    policy_version="1",
                )
            }
        )

    def health(self, *, meta: Any):
        from lib.shared.envelope import success

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


class _FakeVaultService:
    """Minimal fake that responds to list_directory."""

    def list_directory(self, *, meta: EnvelopeMeta, directory_path: str) -> Envelope:
        return Envelope(
            metadata=meta,
            payload=Payload(value=[]),
            errors=[],
        )


def _write_op_manifest(
    root: Path,
    capability_id: str,
    call_target: str,
    input_schema: dict | None,
    output_schema: dict | None,
) -> None:
    pkg = root / capability_id
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "capability.json").write_text(
        json.dumps(
            {
                "capability_id": capability_id,
                "kind": "native_op",
                "version": "1.0.0",
                "summary": f"Test op {capability_id}",
                "input_schema": input_schema,
                "output_schema": output_schema,
                "call_target": call_target,
            }
        ),
        encoding="utf-8",
    )
    (pkg / "README.md").write_text(f"# {capability_id}", encoding="utf-8")


def _write_skill_manifest(root: Path, capability_id: str) -> None:
    pkg = root / capability_id
    (pkg / "test").mkdir(parents=True, exist_ok=True)
    (pkg / "capability.json").write_text(
        json.dumps(
            {
                "capability_id": capability_id,
                "kind": "logic_skill",
                "version": "1.0.0",
                "summary": f"Test skill {capability_id}",
            }
        ),
        encoding="utf-8",
    )
    (pkg / "README.md").write_text(f"# {capability_id}", encoding="utf-8")
    (pkg / "execute.py").write_text(
        "def execute():\n    return {'ok': True}\n",
        encoding="utf-8",
    )
    (pkg / "test" / f"test_{capability_id.replace('-', '_')}.py").write_text(
        "def test_placeholder():\n    assert True\n",
        encoding="utf-8",
    )


def _write_pipeline_manifest(
    root: Path,
    capability_id: str,
    pipeline: list[str],
    input_schema: dict | None,
    output_schema: dict | None,
) -> None:
    pkg = root / capability_id
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "capability.json").write_text(
        json.dumps(
            {
                "capability_id": capability_id,
                "kind": "pipeline_skill",
                "version": "1.0.0",
                "summary": f"Test pipeline {capability_id}",
                "input_schema": input_schema,
                "output_schema": output_schema,
                "pipeline": pipeline,
            }
        ),
        encoding="utf-8",
    )
    (pkg / "README.md").write_text(f"# {capability_id}", encoding="utf-8")


def _sentinel_handler(
    request: CapabilityInvocationRequest,
    runtime: object,
) -> CapabilityExecutionResponse:
    return CapabilityExecutionResponse(output={"sentinel": True})


def test_after_boot_registers_handlers_for_op_manifests(tmp_path) -> None:
    _write_op_manifest(
        tmp_path,
        "test-op",
        "service_vault_authority.list_directory",
        {"directory_path": "string | path to list"},
        {"type": "array", "items": {"type": "object", "title": "VaultEntry"}},
    )

    registry = CapabilityRegistry()
    service = DefaultCapabilityEngineService(
        settings=CapabilityEngineSettings(discovery_root=str(tmp_path)),
        policy_service=_FakePolicyService(),
        registry=registry,
    )

    components = {
        "service_capability_engine": service,
        "service_vault_authority": _FakeVaultService(),
    }

    after_boot(settings=_settings(), components=components)

    assert registry.resolve_handler(capability_id="test-op") is not None


def test_after_boot_registers_handlers_for_logic_skills(tmp_path) -> None:
    _write_skill_manifest(tmp_path, "test-skill")
    registry = CapabilityRegistry()
    service = DefaultCapabilityEngineService(
        settings=CapabilityEngineSettings(discovery_root=str(tmp_path)),
        policy_service=_FakePolicyService(),
        registry=registry,
    )

    components = {
        "service_capability_engine": service,
    }

    after_boot(settings=_settings(), components=components)

    assert registry.resolve_handler(capability_id="test-skill") is not None


def test_after_boot_registers_handlers_for_pipeline_skills(tmp_path) -> None:
    list_directory_output = {
        "type": "array",
        "items": {"type": "object", "title": "VaultEntry"},
    }
    _write_op_manifest(
        tmp_path,
        "test-op",
        "service_vault_authority.list_directory",
        {"directory_path": "string | path to list"},
        list_directory_output,
    )
    _write_pipeline_manifest(
        tmp_path,
        "test-pipeline",
        ["test-op"],
        {"directory_path": "string | path to list"},
        list_directory_output,
    )

    registry = CapabilityRegistry()
    service = DefaultCapabilityEngineService(
        settings=CapabilityEngineSettings(discovery_root=str(tmp_path)),
        policy_service=_FakePolicyService(),
        registry=registry,
    )

    components = {
        "service_capability_engine": service,
        "service_vault_authority": _FakeVaultService(),
    }

    after_boot(settings=_settings(), components=components)

    assert registry.resolve_handler(capability_id="test-pipeline") is not None


def test_after_boot_does_not_overwrite_existing_handlers(tmp_path) -> None:
    _write_op_manifest(
        tmp_path,
        "test-op",
        "service_vault_authority.list_directory",
        {"directory_path": "string | path to list"},
        {"type": "array", "items": {"type": "object", "title": "VaultEntry"}},
    )

    registry = CapabilityRegistry()
    service = DefaultCapabilityEngineService(
        settings=CapabilityEngineSettings(discovery_root=str(tmp_path)),
        policy_service=_FakePolicyService(),
        registry=registry,
    )

    # Manually discover + register handler before after_boot
    registry.discover(root=tmp_path)
    registry.register_handler(capability_id="test-op", handler=_sentinel_handler)

    # Monkey-patch _load_capabilities to no-op since already loaded
    service._load_capabilities = lambda: None  # type: ignore[assignment]

    components = {
        "service_capability_engine": service,
        "service_vault_authority": _FakeVaultService(),
    }

    after_boot(settings=_settings(), components=components)

    resolved = registry.resolve_handler(capability_id="test-op")
    assert resolved is _sentinel_handler
