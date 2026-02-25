"""Capability registry loading immutable manifests and runtime handlers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import inspect
import json
from pathlib import Path
from typing import Any, Protocol, get_args, get_origin

from services.action.capability_engine.domain import (
    CapabilityExecutionResponse,
    CapabilityManifest,
    OpCapabilityManifest,
    SkillCapabilityManifest,
)
from services.action.language_model.service import LanguageModelService
from services.action.policy_service.service import PolicyService
from services.action.attention_router.service import AttentionRouterService
from services.action.switchboard.service import SwitchboardService
from services.action.policy_service.domain import CapabilityInvocationRequest
from services.state.cache_authority.service import CacheAuthorityService
from services.state.embedding_authority.service import EmbeddingAuthorityService
from services.state.memory_authority.service import MemoryAuthorityService
from services.state.object_authority.service import ObjectAuthorityService
from services.state.vault_authority.service import VaultAuthorityService


class CapabilityRuntime(Protocol):
    """Runtime helper contract exposed to capability handlers."""

    def invoke_nested(
        self,
        *,
        capability_id: str,
        input_payload: dict[str, Any],
    ) -> CapabilityExecutionResponse:
        """Invoke a nested capability under narrowed lineage context."""


CapabilityHandler = Callable[
    [CapabilityInvocationRequest, CapabilityRuntime], CapabilityExecutionResponse
]


@dataclass(frozen=True, slots=True)
class CallTargetContract:
    """Contract for one callable target used by Op capability manifests."""

    input_types: tuple[str, ...]
    output_types: tuple[str, ...]


class CapabilityRegistry:
    """In-memory capability registry backed by manifest discovery and handlers."""

    def __init__(self) -> None:
        self._manifests: dict[str, CapabilityManifest] = {}
        self._handlers: dict[str, CapabilityHandler] = {}

    def discover(
        self,
        *,
        root: Path,
        call_targets: dict[str, CallTargetContract] | None = None,
    ) -> None:
        """Auto-discover ``capability.json`` declarations under one root."""
        if not root.exists():
            return

        discovered: dict[str, CapabilityManifest] = {}
        for package_dir in sorted(path for path in root.iterdir() if path.is_dir()):
            manifest_path = package_dir / "capability.json"
            if not manifest_path.exists():
                continue
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = self._parse_manifest(raw)
            self._validate_manifest_files(package_dir=package_dir, manifest=manifest)
            if manifest.capability_id in discovered:
                raise ValueError(f"duplicate capability id: {manifest.capability_id}")
            discovered[manifest.capability_id] = manifest

        self._validate_closure(discovered)
        self._validate_call_targets_and_io(
            manifests=discovered,
            call_targets=self._build_call_target_contracts(extra=call_targets),
        )
        self._manifests = discovered

    def _parse_manifest(self, raw: dict[str, Any]) -> CapabilityManifest:
        kind = raw.get("kind")
        if kind == "op":
            return OpCapabilityManifest.model_validate(raw)
        if kind == "skill":
            return SkillCapabilityManifest.model_validate(raw)
        raise ValueError("capability manifest kind must be 'op' or 'skill'")

    def _validate_manifest_files(
        self,
        *,
        package_dir: Path,
        manifest: CapabilityManifest,
    ) -> None:
        if package_dir.name != manifest.capability_id:
            raise ValueError(
                "capability package directory must match manifest capability_id"
            )

        readme_path = package_dir / "README.md"
        if not readme_path.exists():
            raise ValueError(
                f"capability package missing README.md: {manifest.capability_id}"
            )

        if isinstance(manifest, SkillCapabilityManifest):
            if manifest.skill_type == "logic":
                entrypoint = package_dir / manifest.entrypoint
                if not entrypoint.exists():
                    raise ValueError(
                        f"logic skill missing entrypoint: {manifest.capability_id}"
                    )
                has_tests = any((package_dir / "test").glob("test_*.py"))
                if not has_tests:
                    raise ValueError(
                        f"logic skill missing tests: {manifest.capability_id}"
                    )
            elif manifest.skill_type == "pipeline" and len(manifest.pipeline) == 0:
                raise ValueError(
                    f"pipeline skill must declare pipeline entries: {manifest.capability_id}"
                )

    def _validate_closure(self, manifests: dict[str, CapabilityManifest]) -> None:
        manifest_ids = set(manifests.keys())
        for capability_id, manifest in manifests.items():
            for dependency in manifest.required_capabilities:
                if dependency not in manifest_ids:
                    raise ValueError(
                        f"capability {capability_id} requires unknown dependency {dependency}"
                    )
            if isinstance(manifest, SkillCapabilityManifest):
                for nested in manifest.pipeline:
                    if nested not in manifest_ids:
                        raise ValueError(
                            f"pipeline skill {capability_id} references unknown capability {nested}"
                        )

    def _validate_call_targets_and_io(
        self,
        *,
        manifests: dict[str, CapabilityManifest],
        call_targets: dict[str, CallTargetContract],
    ) -> None:
        for capability_id, manifest in manifests.items():
            if isinstance(manifest, OpCapabilityManifest):
                contract = call_targets.get(manifest.call_target)
                if contract is None:
                    raise ValueError(
                        f"op capability {capability_id} references unknown call target {manifest.call_target}"
                    )
                if manifest.input_types != contract.input_types:
                    raise ValueError(
                        f"op capability {capability_id} input types do not match call target {manifest.call_target}"
                    )
                if manifest.output_types != contract.output_types:
                    raise ValueError(
                        f"op capability {capability_id} output types do not match call target {manifest.call_target}"
                    )
                continue

            if manifest.skill_type != "pipeline":
                continue
            if len(manifest.pipeline) == 0:
                continue

            first = manifests[manifest.pipeline[0]]
            if manifest.input_types != first.input_types:
                raise ValueError(
                    f"pipeline skill {capability_id} input types must match first call target {first.capability_id}"
                )
            for index in range(1, len(manifest.pipeline)):
                previous = manifests[manifest.pipeline[index - 1]]
                current = manifests[manifest.pipeline[index]]
                if previous.output_types != current.input_types:
                    raise ValueError(
                        f"pipeline skill {capability_id} has incompatible call targets {previous.capability_id} -> {current.capability_id}"
                    )
            last = manifests[manifest.pipeline[-1]]
            if manifest.output_types != last.output_types:
                raise ValueError(
                    f"pipeline skill {capability_id} output types must match final call target {last.capability_id}"
                )

    def _build_call_target_contracts(
        self, *, extra: dict[str, CallTargetContract] | None
    ) -> dict[str, CallTargetContract]:
        contracts = self._discover_native_service_targets()
        if extra:
            contracts.update(extra)
        return contracts

    def _discover_native_service_targets(self) -> dict[str, CallTargetContract]:
        contracts: dict[str, CallTargetContract] = {}
        services: tuple[tuple[str, type[Any]], ...] = (
            ("service_cache_authority", CacheAuthorityService),
            ("service_embedding_authority", EmbeddingAuthorityService),
            ("service_memory_authority", MemoryAuthorityService),
            ("service_object_authority", ObjectAuthorityService),
            ("service_vault_authority", VaultAuthorityService),
            ("service_language_model", LanguageModelService),
            ("service_policy_service", PolicyService),
            ("service_attention_router", AttentionRouterService),
            ("service_switchboard", SwitchboardService),
        )
        for component_id, service_cls in services:
            for method_name, contract in self._service_target_contracts(
                service_cls=service_cls
            ).items():
                key = f"{component_id}.{method_name}"
                contracts[key] = contract
        return contracts

    def _service_target_contracts(
        self, *, service_cls: type[Any]
    ) -> dict[str, CallTargetContract]:
        contracts: dict[str, CallTargetContract] = {}
        for method_name, method in inspect.getmembers(
            service_cls, predicate=inspect.isfunction
        ):
            if method_name.startswith("_"):
                continue
            signature = inspect.signature(method)
            input_types = tuple(
                self._annotation_name(parameter.annotation)
                for parameter in signature.parameters.values()
                if parameter.name not in {"self", "meta"}
            )
            if len(input_types) == 0:
                input_types = ("none",)
            output_types = self._return_types(signature.return_annotation)
            contracts[method_name] = CallTargetContract(
                input_types=input_types,
                output_types=output_types,
            )
        return contracts

    def _return_types(self, annotation: Any) -> tuple[str, ...]:
        if annotation is inspect.Signature.empty:
            return ("any",)
        if isinstance(annotation, str):
            normalized = annotation.strip()
            if normalized.startswith("Envelope[") and normalized.endswith("]"):
                return (normalized.removeprefix("Envelope[").removesuffix("]"),)
            return (normalized,)
        origin = get_origin(annotation)
        args = get_args(annotation)
        if (
            origin is not None
            and getattr(origin, "__name__", "") == "Envelope"
            and args
        ):
            return (self._annotation_name(args[0]),)
        return (self._annotation_name(annotation),)

    def _annotation_name(self, annotation: Any) -> str:
        if annotation is inspect.Signature.empty:
            return "any"
        if isinstance(annotation, str):
            return annotation
        origin = get_origin(annotation)
        if origin is None:
            return getattr(annotation, "__name__", str(annotation))
        args = get_args(annotation)
        origin_name = getattr(origin, "__name__", str(origin))
        if len(args) == 0:
            return origin_name
        return f"{origin_name}[{', '.join(self._annotation_name(arg) for arg in args)}]"

    def register_manifest(self, *, manifest: CapabilityManifest) -> None:
        """Register one manifest directly without filesystem discovery."""
        self._manifests[manifest.capability_id] = manifest

    def register_handler(
        self,
        *,
        capability_id: str,
        handler: CapabilityHandler,
    ) -> None:
        """Register one runtime handler for an existing capability manifest."""
        self._handlers[capability_id] = handler

    def resolve_manifest(self, *, capability_id: str) -> CapabilityManifest | None:
        """Resolve one capability manifest by package capability identifier."""
        return self._manifests.get(capability_id)

    def resolve_handler(self, *, capability_id: str) -> CapabilityHandler | None:
        """Resolve one capability handler by package capability identifier."""
        return self._handlers.get(capability_id)

    def count(self) -> int:
        """Return number of discovered capability manifests."""
        return len(self._manifests)
