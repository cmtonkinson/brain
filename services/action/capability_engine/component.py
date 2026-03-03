"""Component declaration for Capability Engine Service."""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path

from packages.brain_shared.config import CoreRuntimeSettings
from packages.brain_shared.manifest import (
    ComponentId,
    ModuleRoot,
    ServiceManifest,
    register_component,
)

SERVICE_COMPONENT_ID = ComponentId("service_capability_engine")

MANIFEST = register_component(
    ServiceManifest(
        id=SERVICE_COMPONENT_ID,
        layer=1,
        system="action",
        module_roots=frozenset({ModuleRoot("services.action.capability_engine")}),
        public_api_roots=frozenset(
            {ModuleRoot("services.action.capability_engine.service")}
        ),
        owns_resources=frozenset({ComponentId("adapter_utcp_code_mode")}),
    )
)


def build_component(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered service component."""
    from services.action.capability_engine.service import (
        build_capability_engine_service,
    )
    from services.action.policy_service.service import PolicyService

    policy_service = components.get("service_policy_service")
    if not isinstance(policy_service, PolicyService):
        raise KeyError("service_policy_service")

    return build_capability_engine_service(
        settings=settings,
        policy_service=policy_service,
        code_mode_adapter=components.get("adapter_utcp_code_mode"),
    )


def after_boot(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> None:
    """Load capability manifests and auto-register Op handlers."""
    from services.action.capability_engine.domain import OpCapabilityManifest
    from services.action.capability_engine.domain import SkillCapabilityManifest
    from services.action.capability_engine.implementation import (
        DefaultCapabilityEngineService,
    )
    from services.action.capability_engine.logic_handler_bridge import (
        build_logic_skill_handler,
    )
    from services.action.capability_engine.op_handler_bridge import build_op_handler
    from services.action.capability_engine.pipeline_handler_bridge import (
        build_pipeline_skill_handler,
    )

    service = components.get(str(SERVICE_COMPONENT_ID))
    if not isinstance(service, DefaultCapabilityEngineService):
        raise RuntimeError("service_capability_engine is missing or invalid")
    service._load_capabilities()
    package_dirs = _discover_capability_package_dirs(
        root=Path(service._settings.discovery_root)
    )

    for manifest in service._registry.list_manifests():
        if (
            service._registry.resolve_handler(capability_id=manifest.capability_id)
            is not None
        ):
            continue
        if isinstance(manifest, OpCapabilityManifest):
            handler = build_op_handler(
                call_target=manifest.call_target,
                components=components,
            )
            service._registry.register_handler(
                capability_id=manifest.capability_id,
                handler=handler,
            )
            continue
        if (
            isinstance(manifest, SkillCapabilityManifest)
            and manifest.kind == "logic_skill"
        ):
            package_dir = package_dirs.get(manifest.capability_id)
            if package_dir is None:
                raise RuntimeError(
                    f"logic skill package directory not found: {manifest.capability_id}"
                )
            handler = build_logic_skill_handler(
                capability_id=manifest.capability_id,
                package_dir=package_dir,
                entrypoint=manifest.entrypoint,
                components=components,
            )
            service._registry.register_handler(
                capability_id=manifest.capability_id,
                handler=handler,
            )
            continue
        if (
            isinstance(manifest, SkillCapabilityManifest)
            and manifest.kind == "pipeline_skill"
        ):
            handler = build_pipeline_skill_handler(
                manifest=manifest,
                registry=service._registry,
            )
            service._registry.register_handler(
                capability_id=manifest.capability_id,
                handler=handler,
            )


def _discover_capability_package_dirs(*, root: Path) -> dict[str, Path]:
    """Return package directories keyed by capability_id from one discovery root."""
    package_dirs: dict[str, Path] = {}
    if not root.exists():
        return package_dirs
    for manifest_path in sorted(root.rglob("capability.json")):
        package_dir = manifest_path.parent
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        if raw.get("enabled", True) is False:
            continue
        capability_id = raw.get("capability_id")
        if not isinstance(capability_id, str) or capability_id == "":
            continue
        package_dirs[capability_id] = package_dir
    return package_dirs
