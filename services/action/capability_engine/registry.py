"""Capability registry loading immutable manifests and runtime handlers."""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
from typing import Any, Protocol

from services.action.capability_engine.domain import (
    CapabilityExecutionResponse,
    CapabilityManifest,
    OpCapabilityManifest,
    SkillCapabilityManifest,
)
from services.action.policy_service.domain import CapabilityInvocationRequest


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


class CapabilityRegistry:
    """In-memory capability registry backed by manifest discovery and handlers."""

    def __init__(self) -> None:
        self._manifests: dict[str, CapabilityManifest] = {}
        self._handlers: dict[str, CapabilityHandler] = {}

    def discover(self, *, root: Path) -> None:
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
