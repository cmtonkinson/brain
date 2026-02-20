"""Static checks for public API invocation instrumentation decorators.

These checks enforce that each registered service implementation decorates all
public methods in its declared Service API contracts with shared public API
instrumentation.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.brain_shared.component_loader import import_registered_component_modules
from packages.brain_shared.manifest import ServiceManifest, get_registry


def test_registered_services_decorate_public_api_methods() -> None:
    """Require instrumentation on all public methods declared in Service APIs."""
    repo_root = Path.cwd().resolve()
    services = _load_services()

    failures: list[str] = []
    for service in services:
        contract_methods = _service_contract_public_methods(
            repo_root=repo_root,
            service=service,
        )
        if len(contract_methods) == 0:
            continue

        decorated_methods = _service_decorated_methods(
            repo_root=repo_root,
            service=service,
        )
        missing = sorted(contract_methods - decorated_methods)
        if missing:
            failures.append(f"{service.id}: {missing}")

    assert not failures, (
        "Missing @public_api_instrumented on Service public API methods:\n"
        + "\n".join(failures)
    )


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


def _load_services() -> tuple[ServiceManifest, ...]:
    """Import component manifests and return registered service manifests."""
    import_registered_component_modules()
    registry = get_registry()
    registry.assert_valid()
    return registry.list_services()


def _service_contract_public_methods(
    *, repo_root: Path, service: ServiceManifest
) -> set[str]:
    """Return public method names declared by service API contract classes."""
    names: set[str] = set()
    for root in sorted(str(item) for item in service.public_api_roots):
        service_file = _module_to_file(repo_root=repo_root, module=f"{root}.service")
        contract_files: tuple[Path, ...]
        if service_file is not None:
            contract_files = (service_file,)
        else:
            api_file = _module_to_file(repo_root=repo_root, module=f"{root}.api")
            contract_files = (api_file,) if api_file is not None else ()

        for file_path in contract_files:
            module = ast.parse(file_path.read_text(encoding="utf-8"))
            for node in module.body:
                if not isinstance(node, ast.ClassDef):
                    continue
                if not _looks_like_service_contract(node):
                    continue
                for child in node.body:
                    if not isinstance(child, ast.FunctionDef):
                        continue
                    if child.name.startswith("_"):
                        continue
                    names.add(child.name)
    return names


def _service_decorated_methods(
    *, repo_root: Path, service: ServiceManifest
) -> set[str]:
    """Return public method names decorated in service implementation modules."""
    names: set[str] = set()
    for root in sorted(str(item) for item in service.module_roots):
        file_path = _module_to_file(
            repo_root=repo_root, module=f"{root}.implementation"
        )
        if file_path is None:
            continue

        module = ast.parse(file_path.read_text(encoding="utf-8"))
        for node in module.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for child in node.body:
                if not isinstance(child, ast.FunctionDef):
                    continue
                if child.name.startswith("_"):
                    continue
                if _has_public_api_instrumented(child):
                    names.add(child.name)
    return names


def _module_to_file(*, repo_root: Path, module: str) -> Path | None:
    """Resolve one Python module name to a repo-relative file path."""
    path = repo_root / (module.replace(".", "/") + ".py")
    if path.exists():
        return path
    return None


def _looks_like_service_contract(node: ast.ClassDef) -> bool:
    """Return True when a class appears to define a Service API contract."""
    if node.name.endswith("Service"):
        return True

    for child in node.body:
        if not isinstance(child, ast.FunctionDef):
            continue
        for decorator in child.decorator_list:
            if isinstance(decorator, ast.Name) and decorator.id == "abstractmethod":
                return True
            if (
                isinstance(decorator, ast.Attribute)
                and decorator.attr == "abstractmethod"
            ):
                return True
    return False


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
