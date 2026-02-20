"""System-level static checks banning dynamic import mechanisms.

Dynamic imports reduce determinism and weaken static boundary enforcement. This
module disallows importlib-based and builtin ``__import__`` usage in runtime
code.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.shared.static_analysis_helpers import (
    _RUNTIME_SCAN_ROOTS,
    discover_runtime_python_files,
    module_name_for_file,
)

_DYNAMIC_IMPORT_ALLOWLIST = (
    # component_loader.py is the only exception, and it needs dynamic imports
    # because it's responsible for kicking off Component discovery and
    # self-registration.
    "packages/brain_shared/component_loader.py",
)


@dataclass(frozen=True)
class _Violation:
    """One dynamic-import violation with stable source context."""

    file_path: Path
    line: int
    message: str

    def format(self) -> str:
        """Render violation for assertion output."""
        return f"{self.file_path}:{self.line}: {self.message}"


def test_runtime_code_disallows_dynamic_imports() -> None:
    """Reject dynamic import usage in runtime code roots."""
    repo_root = Path.cwd().resolve()
    runtime_files = discover_runtime_python_files(
        repo_root=repo_root, roots=_RUNTIME_SCAN_ROOTS
    )

    violations: list[_Violation] = []
    for file_path in runtime_files:
        rel_path = file_path.relative_to(repo_root).as_posix()
        if rel_path in _DYNAMIC_IMPORT_ALLOWLIST:
            continue
        source = file_path.read_text(encoding="utf-8")
        caller_module = module_name_for_file(repo_root=repo_root, file_path=file_path)
        violations.extend(
            _analyze_source_for_dynamic_imports(
                source=source,
                caller_module=caller_module,
                file_path=file_path,
            )
        )

    assert not violations, "\n".join(v.format() for v in violations)


def test_dynamic_import_allowlist_is_narrow_and_intentional() -> None:
    """Allowlist must remain limited to the component bootstrap import path."""
    assert _DYNAMIC_IMPORT_ALLOWLIST == ("packages/brain_shared/component_loader.py",)

    source = Path("packages/brain_shared/component_loader.py").read_text(
        encoding="utf-8"
    )
    assert "import importlib" in source
    assert "importlib.import_module(" in source


def _analyze_source_for_dynamic_imports(
    *, source: str, caller_module: str, file_path: Path
) -> list[_Violation]:
    """Return dynamic-import violations found in one Python source module."""
    del caller_module
    tree = ast.parse(source, filename=str(file_path))

    importlib_aliases: set[str] = set()
    imported_dynamic_helpers: set[str] = set()

    violations: list[_Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "importlib" or alias.name.startswith("importlib."):
                    as_name = alias.asname or alias.name.split(".", maxsplit=1)[0]
                    importlib_aliases.add(as_name)
                    violations.append(
                        _Violation(
                            file_path=file_path,
                            line=node.lineno,
                            message=f"Dynamic import module is banned: import '{alias.name}'",
                        )
                    )
            continue

        if isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            if module_name == "importlib" or module_name.startswith("importlib."):
                violations.append(
                    _Violation(
                        file_path=file_path,
                        line=node.lineno,
                        message=f"Dynamic import module is banned: from '{module_name}'",
                    )
                )
                for alias in node.names:
                    imported_dynamic_helpers.add(alias.asname or alias.name)
            continue

        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                if func.id == "__import__":
                    violations.append(
                        _Violation(
                            file_path=file_path,
                            line=node.lineno,
                            message="Builtin '__import__' is banned",
                        )
                    )
                if func.id in imported_dynamic_helpers:
                    violations.append(
                        _Violation(
                            file_path=file_path,
                            line=node.lineno,
                            message=f"Dynamic import helper call is banned: '{func.id}(...)'",
                        )
                    )
                continue

            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                if func.value.id in importlib_aliases:
                    violations.append(
                        _Violation(
                            file_path=file_path,
                            line=node.lineno,
                            message=(
                                "Dynamic importlib usage is banned: "
                                f"'{func.value.id}.{func.attr}(...)'"
                            ),
                        )
                    )

    return violations
