"""System-level static checks for service public API import boundaries.

This module enforces that runtime code may only import a service through that
service's ``public_api_roots``. Any import into a service-private module from
outside the owning service component is rejected.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.brain_shared.component_loader import import_registered_component_modules
from packages.brain_shared.manifest import ServiceManifest, get_registry
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
    """One public-boundary import violation with stable source context."""

    file_path: Path
    line: int
    message: str

    def format(self) -> str:
        """Render one violation line for assertion output."""
        return f"{self.file_path}:{self.line}: {self.message}"


@dataclass(frozen=True)
class _ServiceBoundary:
    """Resolved module-root/public-root boundary for one registered service."""

    service_id: str
    schema_name: str
    module_roots: tuple[str, ...]
    public_api_roots: tuple[str, ...]

    def owns_module(self, module_name: str) -> bool:
        """Return whether the given module belongs to this service component."""
        return any(is_equal_or_child(module_name, root) for root in self.module_roots)

    def is_public_module(self, module_name: str) -> bool:
        """Return whether a module is within this service's published API roots."""
        return any(
            is_equal_or_child(module_name, root) for root in self.public_api_roots
        )

    def is_private_module(self, module_name: str) -> bool:
        """Return whether a module is owned by the service but not publicly exposed."""
        return self.owns_module(module_name) and not self.is_public_module(module_name)


def test_runtime_code_imports_only_service_public_api_surfaces() -> None:
    """Reject imports from runtime code into service-private modules."""
    repo_root = Path.cwd().resolve()

    services = _load_service_boundaries()

    python_modules = _discover_runtime_python_modules(repo_root=repo_root)
    runtime_files = _discover_runtime_python_files(repo_root=repo_root)

    violations: list[_Violation] = []
    for file_path in runtime_files:
        caller_module = module_name_for_file(repo_root=repo_root, file_path=file_path)
        caller_service = _owning_service_for_module(caller_module, services)

        source = file_path.read_text(encoding="utf-8")
        imports = imports_for_source(
            source=source,
            caller_module=caller_module,
            known_modules=python_modules,
        )

        for import_ref in imports:
            target_service = _owning_service_for_module(
                import_ref.module_name, services
            )
            if target_service is None:
                continue
            if not target_service.is_private_module(import_ref.module_name):
                continue

            # Intra-service imports are explicitly allowed.
            if (
                caller_service is not None
                and caller_service.service_id == target_service.service_id
            ):
                continue

            violations.append(
                _Violation(
                    file_path=file_path,
                    line=import_ref.line,
                    message=(
                        "Import of service-private module is prohibited: "
                        f"'{import_ref.module_name}' is private to service "
                        f"'{target_service.service_id}'"
                    ),
                )
            )

    assert not violations, "\n".join(v.format() for v in violations)


def _load_service_boundaries() -> tuple[_ServiceBoundary, ...]:
    """Import manifests and return service boundary declarations."""
    import_registered_component_modules()
    registry = get_registry()
    registry.assert_valid()

    services: list[_ServiceBoundary] = []
    for service in registry.list_services():
        services.append(_service_boundary_from_manifest(service))
    return tuple(services)


def _service_boundary_from_manifest(service: ServiceManifest) -> _ServiceBoundary:
    """Build one test-oriented service boundary from a service manifest."""
    return _ServiceBoundary(
        service_id=str(service.id),
        schema_name=service.schema_name,
        module_roots=tuple(sorted(str(root) for root in service.module_roots)),
        public_api_roots=tuple(sorted(str(root) for root in service.public_api_roots)),
    )


def _discover_runtime_python_files(*, repo_root: Path) -> tuple[Path, ...]:
    """Return first-party runtime Python files included in static boundary checks."""
    return discover_runtime_python_files(repo_root=repo_root, roots=_RUNTIME_SCAN_ROOTS)


def _discover_runtime_python_modules(*, repo_root: Path) -> set[str]:
    """Return known module names for runtime Python files."""
    modules = discover_runtime_python_modules(
        repo_root=repo_root, roots=_RUNTIME_SCAN_ROOTS
    )
    return modules


def _owning_service_for_module(
    module_name: str, services: tuple[_ServiceBoundary, ...]
) -> _ServiceBoundary | None:
    """Return owning service for a module, choosing the most specific match."""
    owners = [service for service in services if service.owns_module(module_name)]
    if len(owners) == 0:
        return None
    return sorted(
        owners,
        key=lambda service: max(len(root) for root in service.module_roots),
        reverse=True,
    )[0]
