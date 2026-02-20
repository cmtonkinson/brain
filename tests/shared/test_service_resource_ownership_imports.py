"""System-level static checks for service-to-resource ownership import rules.

This module enforces that service code may import unowned shared resources, but
for owned resources only the declaring owner service may import them.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.brain_shared.component_loader import import_registered_component_modules
from packages.brain_shared.manifest import (
    ResourceManifest,
    ServiceManifest,
    get_registry,
)
from tests.shared.static_analysis_helpers import (
    _RUNTIME_SCAN_ROOTS,
    discover_runtime_python_files,
    discover_runtime_python_modules,
    imports_for_source,
    is_equal_or_child,
    module_name_for_file,
)


@dataclass(frozen=True)
class _Violation:
    """One ownership import violation with stable source location."""

    file_path: Path
    line: int
    message: str

    def format(self) -> str:
        """Render violation text for assertion output."""
        return f"{self.file_path}:{self.line}: {self.message}"


@dataclass(frozen=True)
class _ServiceBoundary:
    """Service ownership boundary resolved from one service manifest."""

    service_id: str
    module_roots: tuple[str, ...]
    owns_resources: frozenset[str]

    def owns_module(self, module_name: str) -> bool:
        """Return whether one module belongs to this service component."""
        return any(is_equal_or_child(module_name, root) for root in self.module_roots)


@dataclass(frozen=True)
class _ResourceBoundary:
    """Resource ownership boundary resolved from one resource manifest."""

    resource_id: str
    owner_service_id: str | None
    module_roots: tuple[str, ...]

    def owns_module(self, module_name: str) -> bool:
        """Return whether one module belongs to this resource component."""
        return any(is_equal_or_child(module_name, root) for root in self.module_roots)


def test_services_import_only_owned_or_unowned_resources() -> None:
    """Reject service imports into resources owned by other services."""
    repo_root = Path.cwd().resolve()
    services, resources = _load_boundaries()

    known_modules = _discover_known_runtime_modules(repo_root=repo_root)
    service_files = _discover_service_python_files(repo_root=repo_root)

    violations: list[_Violation] = []

    for file_path in service_files:
        caller_module = module_name_for_file(repo_root=repo_root, file_path=file_path)
        caller_service = _owning_service_for_module(caller_module, services)
        if caller_service is None:
            continue

        source = file_path.read_text(encoding="utf-8")
        imports = imports_for_source(
            source=source,
            caller_module=caller_module,
            known_modules=known_modules,
        )

        for import_ref in imports:
            target_resource = _owning_resource_for_module(
                import_ref.module_name, resources
            )
            if target_resource is None:
                continue

            if target_resource.owner_service_id is None:
                # Shared infra is explicitly allowed.
                continue

            if target_resource.resource_id not in caller_service.owns_resources:
                violations.append(
                    _Violation(
                        file_path=file_path,
                        line=import_ref.line,
                        message=(
                            "Service imported owned resource without declaring ownership: "
                            f"service '{caller_service.service_id}' imported "
                            f"'{target_resource.resource_id}' via '{import_ref.module_name}'"
                        ),
                    )
                )
                continue

            if target_resource.owner_service_id != caller_service.service_id:
                violations.append(
                    _Violation(
                        file_path=file_path,
                        line=import_ref.line,
                        message=(
                            "Service imported resource owned by another service: "
                            f"'{target_resource.resource_id}' owner is "
                            f"'{target_resource.owner_service_id}', caller is "
                            f"'{caller_service.service_id}'"
                        ),
                    )
                )

    assert not violations, "\n".join(v.format() for v in violations)


def _load_boundaries() -> tuple[
    tuple[_ServiceBoundary, ...], tuple[_ResourceBoundary, ...]
]:
    """Import manifests and return service/resource boundaries for checks."""
    import_registered_component_modules()
    registry = get_registry()
    registry.assert_valid()

    services: list[_ServiceBoundary] = []
    for service in registry.list_services():
        services.append(_service_boundary(service))

    resources: list[_ResourceBoundary] = []
    for resource in registry.list_resources():
        resources.append(_resource_boundary(resource))

    return tuple(services), tuple(resources)


def _service_boundary(service: ServiceManifest) -> _ServiceBoundary:
    """Project one service manifest into static-analysis boundary metadata."""
    return _ServiceBoundary(
        service_id=str(service.id),
        module_roots=tuple(sorted(str(root) for root in service.module_roots)),
        owns_resources=frozenset(
            str(resource_id) for resource_id in (service.owns_resources or frozenset())
        ),
    )


def _resource_boundary(resource: ResourceManifest) -> _ResourceBoundary:
    """Project one resource manifest into static-analysis boundary metadata."""
    return _ResourceBoundary(
        resource_id=str(resource.id),
        owner_service_id=(
            None
            if resource.owner_service_id is None
            else str(resource.owner_service_id)
        ),
        module_roots=tuple(sorted(str(root) for root in resource.module_roots)),
    )


def _discover_service_python_files(*, repo_root: Path) -> tuple[Path, ...]:
    """Return runtime Python files under ``services/`` for caller analysis."""
    return discover_runtime_python_files(repo_root=repo_root, roots=("services",))


def _discover_known_runtime_modules(*, repo_root: Path) -> set[str]:
    """Return known runtime modules used for import-from resolution."""
    return discover_runtime_python_modules(
        repo_root=repo_root, roots=_RUNTIME_SCAN_ROOTS
    )


def _owning_service_for_module(
    module_name: str, services: tuple[_ServiceBoundary, ...]
) -> _ServiceBoundary | None:
    """Return owning service for a module, preferring most specific roots."""
    owners = [service for service in services if service.owns_module(module_name)]
    if len(owners) == 0:
        return None

    return sorted(
        owners,
        key=lambda service: max(len(root) for root in service.module_roots),
        reverse=True,
    )[0]


def _owning_resource_for_module(
    module_name: str, resources: tuple[_ResourceBoundary, ...]
) -> _ResourceBoundary | None:
    """Return owning resource for a module, preferring most specific roots."""
    owners = [resource for resource in resources if resource.owns_module(module_name)]
    if len(owners) == 0:
        return None

    return sorted(
        owners,
        key=lambda resource: max(len(root) for root in resource.module_roots),
        reverse=True,
    )[0]
