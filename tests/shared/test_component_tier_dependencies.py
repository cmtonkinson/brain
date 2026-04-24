"""System-level static checks for cross-component tier dependency direction.

This module enforces the architectural invariant that component dependencies may
only point to the same tier or downward (higher -> lower). Any dependency from
lower tier to higher tier is rejected.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lib.shared.component_loader import import_registered_component_modules
from lib.shared.manifest import ComponentManifest, get_registry
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
    """One tier-direction violation with stable source location."""

    file_path: Path
    line: int
    message: str

    def format(self) -> str:
        """Render violation for assertion output."""
        return f"{self.file_path}:{self.line}: {self.message}"


@dataclass(frozen=True)
class _ComponentBoundary:
    """Resolved module-root ownership and tier metadata for one component."""

    component_id: str
    tier: int
    module_roots: tuple[str, ...]

    def owns_module(self, module_name: str) -> bool:
        """Return whether module is part of this component's owned roots."""
        return any(is_equal_or_child(module_name, root) for root in self.module_roots)


def test_components_do_not_import_higher_tier_components() -> None:
    """Reject static import edges from lower-tier to higher-tier components."""
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
            if target_component.tier <= caller_component.tier:
                continue

            violations.append(
                _Violation(
                    file_path=file_path,
                    line=import_ref.line,
                    message=(
                        "Higher-tier component dependency is prohibited: "
                        f"'{caller_component.component_id}' (T{caller_component.tier}) "
                        f"imports '{target_component.component_id}' "
                        f"(T{target_component.tier}) via '{import_ref.module_name}'"
                    ),
                )
            )

    assert not violations, "\n".join(v.format() for v in violations)


def _load_component_boundaries() -> tuple[_ComponentBoundary, ...]:
    """Load all registered components as tier-boundary declarations."""
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
        tier=int(component.tier),
        module_roots=tuple(sorted(str(root) for root in component.module_roots)),
    )


def _discover_runtime_python_files(*, repo_root: Path) -> tuple[Path, ...]:
    """Return all runtime Python files included in this tier check."""
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
