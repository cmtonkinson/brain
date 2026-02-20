"""Reusable helpers for repository static-analysis tests.

The utilities in this module provide deterministic file/module discovery and
AST import extraction across runtime roots used by shared invariant tests.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

_RUNTIME_SCAN_ROOTS = ("services", "resources", "actors", "packages")


@dataclass(frozen=True)
class ImportRef:
    """One resolved import target with source-line metadata."""

    module_name: str
    line: int


def discover_runtime_python_files(
    *, repo_root: Path, roots: tuple[str, ...] = _RUNTIME_SCAN_ROOTS
) -> tuple[Path, ...]:
    """Return runtime Python files under selected repo roots."""
    files: set[Path] = set()
    for root_name in roots:
        root = repo_root / root_name
        if not root.exists():
            continue
        for file_path in root.rglob("*.py"):
            rel = file_path.relative_to(repo_root)
            if should_skip_runtime_path(rel):
                continue
            files.add(file_path)
    return tuple(sorted(files))


def discover_runtime_python_modules(
    *, repo_root: Path, roots: tuple[str, ...] = _RUNTIME_SCAN_ROOTS
) -> set[str]:
    """Return known runtime module names under selected roots."""
    return {
        module_name_for_file(repo_root=repo_root, file_path=file_path)
        for file_path in discover_runtime_python_files(repo_root=repo_root, roots=roots)
    }


def should_skip_runtime_path(rel_path: Path) -> bool:
    """Return True for generated/transient/out-of-scope runtime paths."""
    parts = rel_path.parts
    if "deprecated" in parts or "generated" in parts:
        return True
    if "__pycache__" in parts:
        return True
    return any(part.startswith("work-") for part in parts)


def module_name_for_file(*, repo_root: Path, file_path: Path) -> str:
    """Convert repo-relative runtime file path to dotted module name."""
    rel = file_path.relative_to(repo_root)
    if rel.name == "__init__.py":
        return ".".join(rel.parent.parts)
    return ".".join(rel.with_suffix("").parts)


def imports_for_source(
    *, source: str, caller_module: str, known_modules: set[str]
) -> tuple[ImportRef, ...]:
    """Resolve imported modules from Python source using AST analysis."""
    tree = ast.parse(source)
    imports: list[ImportRef] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(ImportRef(module_name=alias.name, line=node.lineno))
            continue

        if isinstance(node, ast.ImportFrom):
            base = resolve_import_from_base(
                caller_module=caller_module,
                level=node.level,
                module=node.module,
            )
            if base is None:
                continue

            if base != "":
                imports.append(ImportRef(module_name=base, line=node.lineno))

            for alias in node.names:
                if alias.name == "*":
                    continue
                candidate = f"{base}.{alias.name}" if base else alias.name
                if candidate in known_modules:
                    imports.append(ImportRef(module_name=candidate, line=node.lineno))

    return tuple(imports)


def resolve_import_from_base(
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


def is_equal_or_child(module_name: str, prefix: str) -> bool:
    """Return True when module equals prefix or is nested below prefix."""
    return module_name == prefix or module_name.startswith(f"{prefix}.")
