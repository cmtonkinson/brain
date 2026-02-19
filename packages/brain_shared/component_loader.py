"""Component-registration discovery and import helpers."""

from __future__ import annotations

import importlib
from pathlib import Path

_DISCOVERY_ROOTS = ("actors", "services", "resources")


def discover_component_modules(repo_root: Path | None = None) -> tuple[str, ...]:
    """Return import paths for explicit component declaration modules."""
    root = (repo_root or Path.cwd()).resolve()
    modules: list[str] = []
    for discovery_root in _DISCOVERY_ROOTS:
        package_root = root / discovery_root
        if not package_root.exists():
            continue
        for component_file in sorted(package_root.rglob("component.py")):
            rel_component = component_file.relative_to(root)
            if _should_skip(rel_component):
                continue
            if not _looks_like_component_registration(component_file):
                continue
            modules.append(_module_name(rel_component))
    return tuple(modules)


def import_component_modules(modules: tuple[str, ...]) -> tuple[str, ...]:
    """Import discovered component modules to trigger registration."""
    imported: list[str] = []
    for module in modules:
        importlib.import_module(module)
        imported.append(module)
    return tuple(imported)


def import_registered_component_modules(
    repo_root: Path | None = None,
) -> tuple[str, ...]:
    """Discover and import all component declaration modules."""
    modules = discover_component_modules(repo_root=repo_root)
    return import_component_modules(modules)


def _looks_like_component_registration(component_file: Path) -> bool:
    """Return True when ``component.py`` appears to declare a component MANIFEST."""
    source = component_file.read_text(encoding="utf-8")
    return "MANIFEST" in source and "register_component(" in source


def _module_name(rel_path: Path) -> str:
    """Convert a repo-relative module path to a dotted Python import path."""
    return ".".join(rel_path.with_suffix("").parts)


def _should_skip(rel_path: Path) -> bool:
    """Exclude transient and generated paths from component discovery."""
    parts = set(rel_path.parts)
    if "deprecated" in parts or "generated" in parts:
        return True
    return any(part.startswith("work-") for part in rel_path.parts)
