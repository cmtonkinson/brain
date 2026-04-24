"""Unit tests for boot-time auto-registration of Op handlers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lib.shared.config import (
    CoreRuntimeSettings,
    CoreSettings,
    ResourcesSettings,
)
from lib.shared.envelope import Envelope, EnvelopeMeta, Payload
from services.effect.execution.component import after_boot
from services.effect.execution.config import ExecutionSettings
from services.effect.execution.domain import OpExecutionResponse
from services.effect.execution.implementation import (
    DefaultExecutionService,
)
from services.effect.execution.registry import OpRegistry
from services.reason.policy.domain import (
    OpInvocationRequest,
    PolicyDecision,
    PolicyExecutionResult,
    PolicyHealthStatus,
)
from services.reason.policy.service import PolicyExecuteCallback, PolicyService


def _settings() -> CoreRuntimeSettings:
    return CoreRuntimeSettings(
        core=CoreSettings(),
        resources=ResourcesSettings(),
    )


class _FakePolicyService(PolicyService):
    def authorize_and_execute(
        self,
        *,
        request: OpInvocationRequest,
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
                    decided_at=datetime.now(UTC),
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
    op_id: str,
    call_target: str,
    input_schema: dict | None,
    output_schema: dict | None,
) -> None:
    pkg = root / op_id
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "op.json").write_text(
        json.dumps(
            {
                "op_id": op_id,
                "kind": "native",
                "version": "1.0.0",
                "summary": f"Test op {op_id}",
                "effect": "read",
                "approval": "never",
                "input_schema": input_schema,
                "output_schema": output_schema,
                "call_target": call_target,
            }
        ),
        encoding="utf-8",
    )
    (pkg / "README.md").write_text(f"# {op_id}", encoding="utf-8")


def _write_logic_op_manifest(root: Path, op_id: str) -> None:
    pkg = root / op_id
    (pkg / "test").mkdir(parents=True, exist_ok=True)
    (pkg / "op.json").write_text(
        json.dumps(
            {
                "op_id": op_id,
                "kind": "logic",
                "version": "1.0.0",
                "summary": f"Test logic op {op_id}",
                "effect": "execute",
                "approval": "never",
            }
        ),
        encoding="utf-8",
    )
    (pkg / "README.md").write_text(f"# {op_id}", encoding="utf-8")
    (pkg / "execute.py").write_text(
        "def execute():\n    return {'ok': True}\n",
        encoding="utf-8",
    )
    (pkg / "test" / f"test_{op_id.replace('-', '_')}.py").write_text(
        "def test_placeholder():\n    assert True\n",
        encoding="utf-8",
    )


def _write_pipeline_manifest(
    root: Path,
    op_id: str,
    pipeline: list[str],
    input_schema: dict | None,
    output_schema: dict | None,
) -> None:
    pkg = root / op_id
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "op.json").write_text(
        json.dumps(
            {
                "op_id": op_id,
                "kind": "pipeline",
                "version": "1.0.0",
                "summary": f"Test pipeline {op_id}",
                "effect": "execute",
                "approval": "never",
                "input_schema": input_schema,
                "output_schema": output_schema,
                "pipeline": pipeline,
            }
        ),
        encoding="utf-8",
    )
    (pkg / "README.md").write_text(f"# {op_id}", encoding="utf-8")


def _sentinel_handler(
    request: OpInvocationRequest,
    runtime: object,
) -> OpExecutionResponse:
    return OpExecutionResponse(output={"sentinel": True})


def test_after_boot_registers_handlers_for_op_manifests(tmp_path) -> None:
    _write_op_manifest(
        tmp_path,
        "test-op",
        "service_vault.list_directory",
        {"directory_path": "string | path to list"},
        {"type": "array", "items": {"type": "object", "title": "VaultEntry"}},
    )

    registry = OpRegistry()
    service = DefaultExecutionService(
        settings=ExecutionSettings(discovery_roots=(str(tmp_path),)),
        policy_service=_FakePolicyService(),
        registry=registry,
    )

    components = {
        "service_execution": service,
        "service_vault": _FakeVaultService(),
    }

    after_boot(settings=_settings(), components=components)

    assert registry.resolve_handler(op_id="test-op") is not None


def test_after_boot_registers_handlers_for_logic_ops(tmp_path) -> None:
    _write_logic_op_manifest(tmp_path, "test-logic")
    registry = OpRegistry()
    service = DefaultExecutionService(
        settings=ExecutionSettings(discovery_roots=(str(tmp_path),)),
        policy_service=_FakePolicyService(),
        registry=registry,
    )

    components = {
        "service_execution": service,
    }

    after_boot(settings=_settings(), components=components)

    assert registry.resolve_handler(op_id="test-logic") is not None


def test_after_boot_registers_handlers_for_pipeline_ops(tmp_path) -> None:
    list_directory_output = {
        "type": "array",
        "items": {"type": "object", "title": "VaultEntry"},
    }
    _write_op_manifest(
        tmp_path,
        "test-op",
        "service_vault.list_directory",
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

    registry = OpRegistry()
    service = DefaultExecutionService(
        settings=ExecutionSettings(discovery_roots=(str(tmp_path),)),
        policy_service=_FakePolicyService(),
        registry=registry,
    )

    components = {
        "service_execution": service,
        "service_vault": _FakeVaultService(),
    }

    after_boot(settings=_settings(), components=components)

    assert registry.resolve_handler(op_id="test-pipeline") is not None


def test_after_boot_does_not_overwrite_existing_handlers(tmp_path) -> None:
    _write_op_manifest(
        tmp_path,
        "test-op",
        "service_vault.list_directory",
        {"directory_path": "string | path to list"},
        {"type": "array", "items": {"type": "object", "title": "VaultEntry"}},
    )

    registry = OpRegistry()
    service = DefaultExecutionService(
        settings=ExecutionSettings(discovery_roots=(str(tmp_path),)),
        policy_service=_FakePolicyService(),
        registry=registry,
    )

    # Manually discover + register handler before after_boot
    registry.discover(roots=(tmp_path,))
    registry.register_handler(op_id="test-op", handler=_sentinel_handler)

    # Monkey-patch _load_ops to no-op since already loaded
    service._load_ops = lambda: None  # type: ignore[assignment]

    components = {
        "service_execution": service,
        "service_vault": _FakeVaultService(),
    }

    after_boot(settings=_settings(), components=components)

    resolved = registry.resolve_handler(op_id="test-op")
    assert resolved is _sentinel_handler
