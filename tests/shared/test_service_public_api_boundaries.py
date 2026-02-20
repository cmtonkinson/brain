"""System-level static checks for service public API import boundaries.

This module enforces that runtime code may only import a service through that
service's ``public_api_roots``. Any import into a service-private module from
outside the owning service component is rejected.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.brain_shared.component_loader import import_registered_component_modules
from packages.brain_shared.manifest import ServiceManifest, get_registry

_RUNTIME_SCAN_ROOTS = ("services", "resources", "actors", "packages")


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
        return any(_is_equal_or_child(module_name, root) for root in self.module_roots)

    def is_public_module(self, module_name: str) -> bool:
        """Return whether a module is within this service's published API roots."""
        return any(_is_equal_or_child(module_name, root) for root in self.public_api_roots)

    def is_private_module(self, module_name: str) -> bool:
        """Return whether a module is owned by the service but not publicly exposed."""
        return self.owns_module(module_name) and not self.is_public_module(module_name)


@dataclass(frozen=True)
class _ImportRef:
    """One resolved imported module candidate with source-location metadata."""

    module_name: str
    line: int


def test_runtime_code_imports_only_service_public_api_surfaces() -> None:
    """Reject imports from runtime code into service-private modules."""
    repo_root = Path.cwd().resolve()

    services = _load_service_boundaries()

    python_modules = _discover_runtime_python_modules(repo_root=repo_root)
    runtime_files = _discover_runtime_python_files(repo_root=repo_root)

    violations: list[_Violation] = []
    for file_path in runtime_files:
        caller_module = _module_name_for_file(repo_root=repo_root, file_path=file_path)
        caller_service = _owning_service_for_module(caller_module, services)

        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
        imports = _imports_for_tree(
            tree=tree,
            caller_module=caller_module,
            known_modules=python_modules,
        )

        for import_ref in imports:
            target_service = _owning_service_for_module(import_ref.module_name, services)
            if target_service is None:
                continue
            if not target_service.is_private_module(import_ref.module_name):
                continue

            # Intra-service imports are explicitly allowed.
            if caller_service is not None and caller_service.service_id == target_service.service_id:
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
    files: set[Path] = set()
    for root_name in _RUNTIME_SCAN_ROOTS:
        root = repo_root / root_name
        if not root.exists():
            continue
        for file_path in root.rglob("*.py"):
            rel = file_path.relative_to(repo_root)
            if _should_skip(rel):
                continue
            files.add(file_path)
    return tuple(sorted(files))


def _discover_runtime_python_modules(*, repo_root: Path) -> set[str]:
    """Return known module names for runtime Python files."""
    modules: set[str] = set()
    for file_path in _discover_runtime_python_files(repo_root=repo_root):
        modules.add(_module_name_for_file(repo_root=repo_root, file_path=file_path))
    return modules


def _should_skip(rel_path: Path) -> bool:
    """Exclude transient/generated/runtime-external code from analysis scope."""
    parts = rel_path.parts
    if "deprecated" in parts or "generated" in parts:
        return True
    if "__pycache__" in parts:
        return True
    return any(part.startswith("work-") for part in parts)


def _module_name_for_file(*, repo_root: Path, file_path: Path) -> str:
    """Convert one repo-relative Python file path to dotted module name."""
    rel = file_path.relative_to(repo_root)
    if rel.name == "__init__.py":
        return ".".join(rel.parent.parts)
    return ".".join(rel.with_suffix("").parts)


def _imports_for_tree(
    *, tree: ast.Module, caller_module: str, known_modules: set[str]
) -> tuple[_ImportRef, ...]:
    """Resolve imported module references from one AST module."""
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
    """Resolve absolute base module for ``from ... import ...`` statements."""
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
    """Return owning service for a module, choosing the most specific match."""
    owners = [service for service in services if service.owns_module(module_name)]
    if len(owners) == 0:
        return None
    return sorted(
        owners,
        key=lambda service: max(len(root) for root in service.module_roots),
        reverse=True,
    )[0]


def _is_equal_or_child(module_name: str, prefix: str) -> bool:
    """Return True when ``module_name`` equals or is nested below ``prefix``."""
    return module_name == prefix or module_name.startswith(f"{prefix}.")
