"""Component declaration for Capability Engine Service."""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path

from lib.shared.config import CoreRuntimeSettings
from lib.shared.manifest import (
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
        owns_resources=frozenset({ComponentId("adapter_mcp")}),
    )
)


def build_component(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered service component."""
    from services.action.capability_engine.service import (
        build_capability_engine_service,
    )
    from services.action.language_model.service import LanguageModelService
    from services.action.policy_service.service import PolicyService
    from services.state.embedding_authority.service import EmbeddingAuthorityService

    policy_service = components.get("service_policy_service")
    if not isinstance(policy_service, PolicyService):
        raise KeyError("service_policy_service")
    language_model_service = components.get("service_language_model")
    if not isinstance(language_model_service, LanguageModelService):
        raise KeyError("service_language_model")
    embedding_authority_service = components.get("service_embedding_authority")
    if not isinstance(embedding_authority_service, EmbeddingAuthorityService):
        raise KeyError("service_embedding_authority")

    return build_capability_engine_service(
        settings=settings,
        policy_service=policy_service,
        language_model_service=language_model_service,
        embedding_authority_service=embedding_authority_service,
        mcp_adapter=components.get("adapter_mcp"),
    )


def after_boot(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> None:
    """Load capability manifests, register MCP tools, and wire handlers."""
    from resources.adapters.mcp.adapter import McpAdapter
    from services.action.capability_engine.domain import OpCapabilityManifest
    from services.action.capability_engine.domain import SkillCapabilityManifest
    from services.action.capability_engine.implementation import (
        DefaultCapabilityEngineService,
    )
    from services.action.capability_engine.logic_handler_bridge import (
        build_logic_skill_handler,
    )
    from services.action.capability_engine.mcp_op_handler_bridge import (
        build_mcp_op_handler,
        is_mcp_call_target,
        parse_mcp_call_target,
    )
    from services.action.capability_engine.mcp_schema_loader import (
        load_mcp_output_schemas,
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

    # Load operator-supplied MCP output schema overrides.
    mcp_output_schemas = load_mcp_output_schemas(
        root=Path(service._settings.discovery_root)
    )

    # Dynamic MCP tool registration from sidecar.
    mcp_adapter = components.get("adapter_mcp")
    if isinstance(mcp_adapter, McpAdapter):
        _register_mcp_tools(
            service=service,
            adapter=mcp_adapter,
            output_schemas=mcp_output_schemas,
        )

    # Register handlers for all discovered manifests.
    for manifest in service._registry.list_manifests():
        if (
            service._registry.resolve_handler(capability_id=manifest.capability_id)
            is not None
        ):
            continue
        if isinstance(manifest, OpCapabilityManifest):
            if is_mcp_call_target(manifest.call_target):
                if isinstance(mcp_adapter, McpAdapter):
                    server_id, tool_name = parse_mcp_call_target(manifest.call_target)
                    handler = build_mcp_op_handler(
                        server_id=server_id,
                        tool_name=tool_name,
                        adapter=mcp_adapter,
                    )
                else:
                    continue
            else:
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


def _register_mcp_tools(
    *,
    service: object,
    adapter: object,
    output_schemas: dict[str, object],
) -> None:
    """Dynamically register each MCP tool as an mcp_op capability."""
    from resources.adapters.mcp.adapter import McpAdapter
    from services.action.capability_engine.domain import OpCapabilityManifest
    from services.action.capability_engine.implementation import (
        DefaultCapabilityEngineService,
    )
    from services.action.capability_engine.mcp_op_handler_bridge import (
        build_mcp_op_handler,
        mcp_capability_id,
    )
    from services.action.capability_engine.mcp_schema_loader import (
        resolve_mcp_output_schema,
    )

    assert isinstance(service, DefaultCapabilityEngineService)
    assert isinstance(adapter, McpAdapter)

    for tool_info in adapter.list_tools():
        capability_id = mcp_capability_id(tool_info.server_id, tool_info.tool_name)
        if service._registry.resolve_manifest(capability_id=capability_id) is not None:
            continue
        output_schema = resolve_mcp_output_schema(output_schemas, tool_info.server_id)
        manifest = OpCapabilityManifest(
            capability_id=capability_id,
            kind="mcp_op",
            version="0.1.0",
            summary=tool_info.description
            or f"{tool_info.server_id} {tool_info.tool_name}",
            call_target=f"mcp:{tool_info.server_id}:{tool_info.tool_name}",
            input_schema=tool_info.input_schema,
            output_schema=output_schema,
            side_effects=("external",),
        )
        service._registry.register_manifest(manifest=manifest)
        handler = build_mcp_op_handler(
            server_id=tool_info.server_id,
            tool_name=tool_info.tool_name,
            adapter=adapter,
        )
        service._registry.register_handler(
            capability_id=capability_id,
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
