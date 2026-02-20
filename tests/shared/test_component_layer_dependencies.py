"""System-level static checks for cross-component layer dependency direction.

This module enforces the architectural invariant that component dependencies may
only point to the same layer or downward (higher -> lower). Any dependency from
lower layer to higher layer is rejected.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.brain_shared.component_loader import import_registered_component_modules
from packages.brain_shared.manifest import ComponentManifest, get_registry

_RUNTIME_SCAN_ROOTS = ("services", "resources", "actors", "packages")


@dataclass(frozen=True)
class _Violation:
    """One layer-direction violation with stable source location."""

    file_path: Path
    line: int
    message: str

    def format(self) -> str:
        """Render violation for assertion output."""
        return f"{self.file_path}:{self.line}: {self.message}"


@dataclass(frozen=True)
class _ComponentBoundary:
    """Resolved module-root ownership and layer metadata for one component."""

    component_id: str
    layer: int
    module_roots: tuple[str, ...]

    def owns_module(self, module_name: str) -> bool:
        """Return whether module is part of this component's owned roots."""
        return any(_is_equal_or_child(module_name, root) for root in self.module_roots)


@dataclass(frozen=True)
class _ImportRef:
    """One resolved import target and source line."""

    module_name: str
    line: int


def test_components_do_not_import_higher_layer_components() -> None:
    """Reject static import edges from lower-layer to higher-layer components."""
    repo_root = Path.cwd().resolve()

    components = _load_component_boundaries()
    runtime_files = _discover_runtime_python_files(repo_root=repo_root)
    known_modules = _discover_runtime_python_modules(repo_root=repo_root)

    violations: list[_Violation] = []
    for file_path in runtime_files:
        caller_module = _module_name_for_file(repo_root=repo_root, file_path=file_path)
        caller_component = _owning_component_for_module(caller_module, components)
        if caller_component is None:
            continue

        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
        imports = _imports_for_tree(
            tree=tree,
            caller_module=caller_module,
            known_modules=known_modules,
        )

        for import_ref in imports:
            target_component = _owning_component_for_module(import_ref.module_name, components)
            if target_component is None:
                # Shared libraries/non-component modules are intentionally exempt.
                continue
            if target_component.component_id == caller_component.component_id:
                continue
            if target_component.layer <= caller_component.layer:
                continue

            violations.append(
                _Violation(
                    file_path=file_path,
                    line=import_ref.line,
                    message=(
                        "Higher-layer component dependency is prohibited: "
                        f"'{caller_component.component_id}' (L{caller_component.layer}) "
                        f"imports '{target_component.component_id}' "
                        f"(L{target_component.layer}) via '{import_ref.module_name}'"
                    ),
                )
            )

    assert not violations, "\n".join(v.format() for v in violations)


def _load_component_boundaries() -> tuple[_ComponentBoundary, ...]:
    """Load all registered components as layer-boundary declarations."""
    import_registered_component_modules()
    registry = get_registry()
    registry.assert_valid()

    boundaries: list[_ComponentBoundary] = []
    for component in registry.list_components():
        boundaries.append(_boundary_from_manifest(component))
    return tuple(boundaries)


def _boundary_from_manifest(component: ComponentManifest) -> _ComponentBoundary:
    """Project a manifest into static-analysis boundary metadata."""
    return _ComponentBoundary(
        component_id=str(component.id),
        layer=int(component.layer),
        module_roots=tuple(sorted(str(root) for root in component.module_roots)),
    )


def _discover_runtime_python_files(*, repo_root: Path) -> tuple[Path, ...]:
    """Return all runtime Python files included in this layer check."""
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
    """Return known runtime module names for import-from resolution."""
    modules: set[str] = set()
    for file_path in _discover_runtime_python_files(repo_root=repo_root):
        modules.add(_module_name_for_file(repo_root=repo_root, file_path=file_path))
    return modules


def _module_name_for_file(*, repo_root: Path, file_path: Path) -> str:
    """Convert runtime file path to canonical dotted module name."""
    rel = file_path.relative_to(repo_root)
    if rel.name == "__init__.py":
        return ".".join(rel.parent.parts)
    return ".".join(rel.with_suffix("").parts)


def _owning_component_for_module(
    module_name: str, components: tuple[_ComponentBoundary, ...]
) -> _ComponentBoundary | None:
    """Return owning component for a module, preferring the most specific root."""
    owners = [component for component in components if component.owns_module(module_name)]
    if len(owners) == 0:
        return None
    return sorted(
        owners,
        key=lambda component: max(len(root) for root in component.module_roots),
        reverse=True,
    )[0]


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


def _is_equal_or_child(module_name: str, prefix: str) -> bool:
    """Return True when module equals prefix or is nested below it."""
    return module_name == prefix or module_name.startswith(f"{prefix}.")


def _should_skip(rel_path: Path) -> bool:
    """Exclude generated/transient/out-of-scope runtime files from checks."""
    parts = rel_path.parts
    if "deprecated" in parts or "generated" in parts:
        return True
    if "__pycache__" in parts:
        return True
    return any(part.startswith("work-") for part in parts)
