"""Component declaration for Execution Service."""

from __future__ import annotations

from collections.abc import Mapping

from lib.shared.config import CoreRuntimeSettings
from lib.shared.manifest import (
    ComponentId,
    ModuleRoot,
    ServiceManifest,
    register_component,
)

SERVICE_COMPONENT_ID = ComponentId("service_execution")

MANIFEST = register_component(
    ServiceManifest(
        id=SERVICE_COMPONENT_ID,
        tier=2,
        plane="effect",
        module_roots=frozenset({ModuleRoot("services.effect.execution")}),
        public_api_roots=frozenset({ModuleRoot("services.effect.execution.service")}),
        owns_resources=frozenset({ComponentId("adapter_mcp")}),
    )
)


def build_component(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered service component."""
    from services.effect.execution.service import (
        build_execution_service,
    )
    from services.effect.language.service import LanguageService
    from services.reason.policy.service import PolicyService
    from services.state.embedding.service import EmbeddingService

    policy_service = components.get("service_policy")
    if not isinstance(policy_service, PolicyService):
        raise KeyError("service_policy")
    language_service = components.get("service_language")
    if not isinstance(language_service, LanguageService):
        raise KeyError("service_language")
    embedding_service = components.get("service_embedding")
    if not isinstance(embedding_service, EmbeddingService):
        raise KeyError("service_embedding")

    return build_execution_service(
        settings=settings,
        policy_service=policy_service,
        language_service=language_service,
        embedding_service=embedding_service,
        mcp_adapter=components.get("adapter_mcp"),
    )


def after_boot(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> None:
    """Load op manifests, register MCP tools, and wire handlers."""
    from resources.adapters.mcp.adapter import McpAdapter
    from services.effect.execution.domain import NativeOpManifest
    from services.effect.execution.domain import CompoundOpManifest
    from services.effect.execution.implementation import (
        DefaultExecutionService,
    )
    from services.effect.execution.logic_handler_bridge import (
        build_logic_op_handler,
    )
    from services.effect.execution.mcp_op_handler_bridge import (
        build_mcp_op_handler,
        is_mcp_call_target,
        parse_mcp_call_target,
    )
    from services.effect.execution.mcp_schema_loader import (
        load_mcp_overrides,
    )
    from services.effect.execution.op_handler_bridge import build_op_handler
    from services.effect.execution.pipeline_handler_bridge import (
        build_pipeline_op_handler,
    )

    service = components.get(str(SERVICE_COMPONENT_ID))
    if not isinstance(service, DefaultExecutionService):
        raise RuntimeError("service_execution is missing or invalid")
    service._load_ops()

    # Load operator-supplied MCP per-tool overrides (effect, approval,
    # output_schema) across all roots and stash on service so lazy syncs
    # (e.g. /mcp, /op-classify) can reuse them without disk I/O.
    service._mcp_overrides = load_mcp_overrides(
        roots=service._effective_discovery_roots()
    )

    # Eager MCP tool registration from sidecar; tolerated as best-effort so a
    # partially-connected sidecar does not block boot. Lazy reconciliation
    # happens later via list_tool_system_hints / classify_dynamic_op.
    mcp_adapter = components.get("adapter_mcp")
    if isinstance(mcp_adapter, McpAdapter):
        service._sync_mcp_tools_quietly()

    # Register handlers for all discovered manifests.
    for manifest in service._registry.list_manifests():
        if service._registry.resolve_handler(op_id=manifest.op_id) is not None:
            continue
        if isinstance(manifest, NativeOpManifest):
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
                op_id=manifest.op_id,
                handler=handler,
            )
            continue
        if isinstance(manifest, CompoundOpManifest) and manifest.kind == "logic":
            package_dir = service._registry.resolve_package_dir(op_id=manifest.op_id)
            if package_dir is None:
                raise RuntimeError(
                    f"logic op package directory not found: {manifest.op_id}"
                )
            handler = build_logic_op_handler(
                op_id=manifest.op_id,
                package_dir=package_dir,
                entrypoint=manifest.entrypoint,
                components=components,
            )
            service._registry.register_handler(
                op_id=manifest.op_id,
                handler=handler,
            )
            continue
        if isinstance(manifest, CompoundOpManifest) and manifest.kind == "pipeline":
            handler = build_pipeline_op_handler(
                manifest=manifest,
                registry=service._registry,
            )
            service._registry.register_handler(
                op_id=manifest.op_id,
                handler=handler,
            )
