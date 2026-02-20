"""System-level static checks for cross-component layer dependency direction.

This module enforces the architectural invariant that component dependencies may
only point to the same layer or downward (higher -> lower). Any dependency from
lower layer to higher layer is rejected.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from packages.brain_shared.component_loader import import_registered_component_modules
from packages.brain_shared.manifest import ComponentManifest, get_registry
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
        return any(is_equal_or_child(module_name, root) for root in self.module_roots)


def test_components_do_not_import_higher_layer_components() -> None:
    """Reject static import edges from lower-layer to higher-layer components."""
    repo_root = Path.cwd().resolve()

    components = _load_component_boundaries()
    runtime_files = _discover_runtime_python_files(repo_root=repo_root)
    known_modules = _discover_runtime_python_modules(repo_root=repo_root)

    violations: list[_Violation] = []
    for file_path in runtime_files:
        caller_module = module_name_for_file(repo_root=repo_root, file_path=file_path)
        caller_component = _owning_component_for_module(caller_module, components)
        if caller_component is None:
            continue

        source = file_path.read_text(encoding="utf-8")
        imports = imports_for_source(
            source=source,
            caller_module=caller_module,
            known_modules=known_modules,
        )

        for import_ref in imports:
            target_component = _owning_component_for_module(
                import_ref.module_name, components
            )
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
    return discover_runtime_python_files(repo_root=repo_root, roots=_RUNTIME_SCAN_ROOTS)


def _discover_runtime_python_modules(*, repo_root: Path) -> set[str]:
    """Return known runtime module names for import-from resolution."""
    return discover_runtime_python_modules(
        repo_root=repo_root, roots=_RUNTIME_SCAN_ROOTS
    )


def _owning_component_for_module(
    module_name: str, components: tuple[_ComponentBoundary, ...]
) -> _ComponentBoundary | None:
    """Return owning component for a module, preferring the most specific root."""
    owners = [
        component for component in components if component.owns_module(module_name)
    ]
    if len(owners) == 0:
        return None
    return sorted(
        owners,
        key=lambda component: max(len(root) for root in component.module_roots),
        reverse=True,
    )[0]
