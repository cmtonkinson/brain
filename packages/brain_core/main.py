"""Process entrypoint for Brain Core startup orchestration."""

from __future__ import annotations

import os
import signal
import sys
import threading
from pathlib import Path
from time import sleep

from fastapi import APIRouter

from packages.brain_core.health_api import register_routes
from packages.brain_core.migrations import run_startup_migrations
from packages.brain_core.startup import run_core_startup
from packages.brain_shared.component_loader import (
    import_component_modules,
    import_registered_component_modules,
)
from packages.brain_shared.config import CoreRuntimeSettings, load_core_runtime_settings
from packages.brain_shared.logging import get_logger
from packages.brain_shared.http.server import create_app, run_app_uds
from packages.brain_shared.manifest import ComponentManifest, get_registry

_LOGGER = get_logger(__name__)
_RUNNING = True


def _handle_shutdown(_signum: int, _frame: object) -> None:
    """Mark process for graceful shutdown when receiving termination signals."""
    global _RUNNING
    _RUNNING = False


def _resolve_component_builder(manifest: ComponentManifest):
    """Load one component module and return its build callable."""
    for module_root in sorted(manifest.module_roots):
        module_name = f"{module_root}.component"
        import_component_modules((module_name,))
        module = sys.modules[module_name]
        builder = getattr(module, "build_component", None)
        if callable(builder):
            return builder
    raise RuntimeError(
        f"component '{manifest.id}' does not expose build_component(...) in its component module"
    )


def _resolve_component_after_boot(manifest: ComponentManifest):
    """Load one optional component-level ``after_boot`` lifecycle callable."""
    for module_root in sorted(manifest.module_roots):
        module_name = f"{module_root}.component"
        import_component_modules((module_name,))
        module = sys.modules[module_name]
        lifecycle = getattr(module, "after_boot", None)
        if callable(lifecycle):
            return lifecycle
    return None


def _resolve_service_http_registrar(manifest: ComponentManifest):
    """Load one optional service-level HTTP registrar from ``api.py``."""
    for module_root in sorted(manifest.module_roots):
        candidate = Path.cwd() / Path(*str(module_root).split(".")) / "api.py"
        if not candidate.exists():
            continue
        module_name = f"{module_root}.api"
        import_component_modules((module_name,))
        module = sys.modules[module_name]
        registrar = getattr(module, "register_routes", None)
        if callable(registrar):
            return registrar
    return None


def _instantiate_registered_components(
    settings: CoreRuntimeSettings,
) -> dict[str, object]:
    """Instantiate all registered L0 resources and L1 services by registry walk."""
    registry = get_registry()
    pending = [*registry.list_resources(), *registry.list_services()]
    built: dict[str, object] = {}

    while pending:
        progressed = False
        next_round: list[ComponentManifest] = []
        for manifest in pending:
            builder = _resolve_component_builder(manifest)
            try:
                built[str(manifest.id)] = builder(settings=settings, components=built)
            except KeyError:
                next_round.append(manifest)
                continue
            progressed = True
            _LOGGER.info(
                "component instantiated",
                extra={"component_id": str(manifest.id), "layer": manifest.layer},
            )

        if not progressed:
            unresolved = ", ".join(str(item.id) for item in next_round)
            raise RuntimeError(
                "unable to resolve component dependency graph; unresolved components: "
                f"{unresolved}"
            )
        pending = next_round
    return built


def _run_after_boot_lifecycle(
    *, settings: CoreRuntimeSettings, components: dict[str, object]
) -> None:
    """Run optional per-component ``after_boot`` lifecycle hooks."""
    registry = get_registry()
    manifests_by_id = {
        str(manifest.id): manifest
        for manifest in [*registry.list_resources(), *registry.list_services()]
    }
    for component_id in components:
        manifest = manifests_by_id.get(component_id)
        if manifest is None:
            raise RuntimeError(
                f"component '{component_id}' is instantiated but missing from registry"
            )
        after_boot = _resolve_component_after_boot(manifest)
        if after_boot is None:
            continue
        after_boot(settings=settings, components=components)
        _LOGGER.info(
            "component after_boot completed", extra={"component_id": component_id}
        )


def _start_http_runtime(
    *,
    settings: CoreRuntimeSettings,
    components: dict[str, object],
) -> tuple[object, threading.Thread]:
    """Start Core HTTP runtime and register all service transport adapters."""
    app = create_app(title="Brain Core API")
    router = APIRouter()

    register_routes(router=router, settings=settings, components=components)

    registry = get_registry()
    registered_services: list[str] = []
    for manifest in sorted(registry.list_services(), key=lambda m: str(m.id)):
        service = components.get(str(manifest.id))
        registrar = _resolve_service_http_registrar(manifest)
        if registrar is None:
            continue
        registrar(router=router, service=service)
        registered_services.append(str(manifest.id))

    app.include_router(router)
    socket_path = settings.core.http.socket_path
    os.makedirs(os.path.dirname(socket_path), exist_ok=True)
    server = run_app_uds(app, socket_path=socket_path)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    _LOGGER.info(
        "core HTTP runtime started",
        extra={
            "socket_path": socket_path,
            "registered_services": registered_services,
        },
    )
    return server, thread


def main() -> None:
    """Discover components, instantiate them, run startup, and hold process."""
    core_config_path = os.getenv("BRAIN_CORE_CONFIG_FILE", "").strip()
    resources_config_path = os.getenv("BRAIN_RESOURCES_CONFIG_FILE", "").strip()
    settings = load_core_runtime_settings(
        core_config_path=Path(core_config_path) if core_config_path else None,
        resources_config_path=Path(resources_config_path)
        if resources_config_path
        else None,
    )

    imported = import_registered_component_modules()
    registry = get_registry()
    registry.assert_valid()
    _LOGGER.info(
        "component registration completed",
        extra={
            "imported_count": len(imported),
            "service_count": len(registry.list_services()),
            "resource_count": len(registry.list_resources()),
        },
    )

    migration_result = None
    if settings.core.boot.run_migrations_on_startup:
        migration_result = run_startup_migrations(settings=settings)

    components = _instantiate_registered_components(settings)
    startup_result = run_core_startup(
        settings=settings,
        resolve_component=lambda component_id: components.get(component_id),
        run_migrations=False,
    )
    _run_after_boot_lifecycle(settings=settings, components=components)
    http_server, http_thread = _start_http_runtime(
        settings=settings, components=components
    )
    _LOGGER.info(
        "brain core startup completed",
        extra={
            "execution_order": startup_result.boot_result.execution_order,
            "migrations_executed": migration_result is not None,
        },
    )

    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)
    try:
        while _RUNNING:
            sleep(1.0)
    finally:
        http_server.should_exit = True
        http_thread.join(timeout=5.0)
        _LOGGER.info("core HTTP runtime stopped")


if __name__ == "__main__":
    main()
