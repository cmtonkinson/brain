"""Static checks for public API invocation instrumentation decorators.

These checks enforce that each public API method defined by the canonical
contracts is decorated with shared public invocation instrumentation.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def test_embedding_authority_public_methods_have_invocation_instrumentation() -> None:
    """Require invocation instrumentation on all EAS contract methods."""
    repo_root = Path.cwd().resolve()
    contract_methods = _public_method_names(
        file_path=repo_root / "services/state/embedding_authority/service.py",
        class_name="EmbeddingAuthorityService",
    )
    decorated_methods = _decorated_public_api_methods(
        file_path=repo_root / "services/state/embedding_authority/implementation.py",
        class_name="DefaultEmbeddingAuthorityService",
    )
    missing = sorted(contract_methods - decorated_methods)
    assert not missing, f"Missing @public_api_instrumented on EAS methods: {missing}"


def test_qdrant_substrate_public_methods_have_invocation_instrumentation() -> None:
    """Require invocation instrumentation on all Qdrant substrate contract methods."""
    repo_root = Path.cwd().resolve()
    contract_methods = _public_method_names(
        file_path=repo_root / "resources/substrates/qdrant/substrate.py",
        class_name="QdrantSubstrate",
    )
    decorated_methods = _decorated_public_api_methods(
        file_path=repo_root / "resources/substrates/qdrant/qdrant_substrate.py",
        class_name="QdrantClientSubstrate",
    )
    missing = sorted(contract_methods - decorated_methods)
    assert not missing, f"Missing @public_api_instrumented on Qdrant methods: {missing}"


def _public_method_names(*, file_path: Path, class_name: str) -> set[str]:
    """Return non-private method names declared directly on one class."""
    class_node = _class_node(file_path=file_path, class_name=class_name)
    names: set[str] = set()
    for node in class_node.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name.startswith("_"):
            continue
        names.add(node.name)
    return names


def _decorated_public_api_methods(*, file_path: Path, class_name: str) -> set[str]:
    """Return method names decorated with ``@public_api_instrumented``."""
    class_node = _class_node(file_path=file_path, class_name=class_name)
    names: set[str] = set()
    for node in class_node.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name.startswith("_"):
            continue
        if _has_public_api_instrumented(node):
            names.add(node.name)
    return names


def _class_node(*, file_path: Path, class_name: str) -> ast.ClassDef:
    """Load and return one named class node from a Python module."""
    source = file_path.read_text(encoding="utf-8")
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node
    raise AssertionError(f"Class not found: {class_name} in {file_path}")


def _has_public_api_instrumented(node: ast.FunctionDef) -> bool:
    """Return whether method decorators include ``@public_api_instrumented``."""
    for decorator in node.decorator_list:
        if (
            isinstance(decorator, ast.Name)
            and decorator.id == "public_api_instrumented"
        ):
            return True
        if (
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Name)
            and decorator.func.id == "public_api_instrumented"
        ):
            return True
    return False
