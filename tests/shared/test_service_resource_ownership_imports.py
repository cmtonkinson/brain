"""System-level static checks for service-to-resource ownership import rules.

This module enforces that service code may import unowned shared resources, but
for owned resources only the declaring owner service may import them.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.brain_shared.component_loader import import_registered_component_modules
from packages.brain_shared.manifest import (
    ComponentId,
    ResourceManifest,
    ServiceManifest,
    get_registry,
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
        return any(_is_equal_or_child(module_name, root) for root in self.module_roots)


@dataclass(frozen=True)
class _ResourceBoundary:
    """Resource ownership boundary resolved from one resource manifest."""

    resource_id: str
    owner_service_id: str | None
    module_roots: tuple[str, ...]

    def owns_module(self, module_name: str) -> bool:
        """Return whether one module belongs to this resource component."""
        return any(_is_equal_or_child(module_name, root) for root in self.module_roots)


@dataclass(frozen=True)
class _ImportRef:
    """One resolved import target and source line."""

    module_name: str
    line: int


def test_services_import_only_owned_or_unowned_resources() -> None:
    """Reject service imports into resources owned by other services."""
    repo_root = Path.cwd().resolve()
    services, resources = _load_boundaries()

    known_modules = _discover_service_python_modules(repo_root=repo_root)
    service_files = _discover_service_python_files(repo_root=repo_root)

    violations: list[_Violation] = []

    for file_path in service_files:
        caller_module = _module_name_for_file(repo_root=repo_root, file_path=file_path)
        caller_service = _owning_service_for_module(caller_module, services)
        if caller_service is None:
            continue

        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
        imports = _imports_for_tree(
            tree=tree,
            caller_module=caller_module,
            known_modules=known_modules,
        )

        for import_ref in imports:
            target_resource = _owning_resource_for_module(import_ref.module_name, resources)
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


def _load_boundaries() -> tuple[tuple[_ServiceBoundary, ...], tuple[_ResourceBoundary, ...]]:
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
        owns_resources=frozenset(str(resource_id) for resource_id in (service.owns_resources or frozenset())),
    )


def _resource_boundary(resource: ResourceManifest) -> _ResourceBoundary:
    """Project one resource manifest into static-analysis boundary metadata."""
    return _ResourceBoundary(
        resource_id=str(resource.id),
        owner_service_id=(
            None if resource.owner_service_id is None else str(ComponentId(resource.owner_service_id))
        ),
        module_roots=tuple(sorted(str(root) for root in resource.module_roots)),
    )


def _discover_service_python_files(*, repo_root: Path) -> tuple[Path, ...]:
    """Return runtime Python files under ``services/`` for caller analysis."""
    root = repo_root / "services"
    files: set[Path] = set()
    if not root.exists():
        return ()

    for file_path in root.rglob("*.py"):
        rel = file_path.relative_to(repo_root)
        if _should_skip(rel):
            continue
        files.add(file_path)

    return tuple(sorted(files))


def _discover_service_python_modules(*, repo_root: Path) -> set[str]:
    """Return known service module names for import-from resolution."""
    modules: set[str] = set()
    for file_path in _discover_service_python_files(repo_root=repo_root):
        modules.add(_module_name_for_file(repo_root=repo_root, file_path=file_path))

    # Include runtime modules outside services so ``from x import y`` resolution can
    # produce concrete module targets when they exist.
    for root_name in ("resources", "actors", "packages"):
        root = repo_root / root_name
        if not root.exists():
            continue
        for file_path in root.rglob("*.py"):
            rel = file_path.relative_to(repo_root)
            if _should_skip(rel):
                continue
            modules.add(_module_name_for_file(repo_root=repo_root, file_path=file_path))

    return modules


def _imports_for_tree(
    *, tree: ast.Module, caller_module: str, known_modules: set[str]
) -> tuple[_ImportRef, ...]:
    """Resolve imported module references from one Python module AST."""
    imports: list[_ImportRef] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(_ImportRef(module_name=alias.name, line=node.lineno))
            continue

        if isinstance(node, ast.ImportFrom):
            base = _resolve_import_from_base(
                caller_module=caller_module,
                level=node.level,
                module=node.module,
            )
            if base is None:
                continue

            if base != "":
                imports.append(_ImportRef(module_name=base, line=node.lineno))

            for alias in node.names:
                if alias.name == "*":
                    continue
                candidate = f"{base}.{alias.name}" if base else alias.name
                if candidate in known_modules:
                    imports.append(_ImportRef(module_name=candidate, line=node.lineno))

    return tuple(imports)


def _resolve_import_from_base(
    *, caller_module: str, level: int, module: str | None
) -> str | None:
    """Resolve absolute base module for one ``from ... import ...`` statement."""
    if level == 0:
        return module

    caller_parts = caller_module.split(".")
    if level > len(caller_parts):
        return None

    prefix = ".".join(caller_parts[: len(caller_parts) - level])
    if module is None:
        return prefix
    if prefix == "":
        return module
    return f"{prefix}.{module}"


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


def _module_name_for_file(*, repo_root: Path, file_path: Path) -> str:
    """Convert one runtime file path to dotted module name."""
    rel = file_path.relative_to(repo_root)
    if rel.name == "__init__.py":
        return ".".join(rel.parent.parts)
    return ".".join(rel.with_suffix("").parts)


def _is_equal_or_child(module_name: str, prefix: str) -> bool:
    """Return True when module equals prefix or is nested below it."""
    return module_name == prefix or module_name.startswith(f"{prefix}.")


def _should_skip(rel_path: Path) -> bool:
    """Exclude out-of-scope paths from static runtime import analysis."""
    parts = rel_path.parts
    if "deprecated" in parts or "generated" in parts:
        return True
    if "__pycache__" in parts:
        return True
    return any(part.startswith("work-") for part in parts)
