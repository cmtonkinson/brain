"""Generate Markdown docs for Core HTTP routes.

The generator parses the route decorators defined in ``lib/core`` and service
API modules and emits a deterministic Markdown inventory of the HTTP surface
mounted by Brain Core.
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

ROUTE_FILES = (
    "lib/core/health_api.py",
    "services/*/*/api.py",
    "services/*/*/_*/api.py",
)
DEFAULT_METADATA = "docs/meta/http-routes.yaml"
DEFAULT_OUTPUT = "docs/http-api.md"
DOC_NAME = "HTTP API"
DOC_TITLE = f"# {DOC_NAME}"
HR = "------------------------------------------------------------------------"
DOC_GENERATED_NOTE = (
    "*This document is generated from `lib/core/health_api.py` and "
    "service API modules, with route intent from `docs/meta/http-routes.yaml`. "
    "Do not edit by hand.*"
)
DOC_EMPTY_MESSAGE = "No Core HTTP routes were found."
CHECK_OUT_OF_DATE_MESSAGE = "HTTP API docs are out of date. Run: make docs"
_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "options", "head"})


@dataclass(frozen=True)
class RouteDoc:
    """One documented FastAPI route."""

    method: str
    path: str
    handler_name: str
    response_model: str
    summary: str


@dataclass(frozen=True)
class ModuleDoc:
    """One documented route module."""

    module_path: str
    routes: list[RouteDoc]


@dataclass(frozen=True)
class RouteMetadata:
    """Human-authored route intent metadata."""

    why: str


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments for generation or drift-check mode."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Output Markdown file path (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--metadata",
        default=DEFAULT_METADATA,
        help=f"Path to route metadata YAML file (default: {DEFAULT_METADATA}).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check whether the generated output matches the current file.",
    )
    return parser.parse_args()


def _first_line(docstring: str | None) -> str:
    """Extract the first non-empty line from a docstring."""
    if not docstring:
        return ""
    for line in docstring.strip().splitlines():
        value = line.strip()
        if value:
            return value
    return ""


def _discover_route_files(repo_root: Path) -> tuple[Path, ...]:
    """Return all source files that may register Core HTTP routes."""
    files: set[Path] = set()
    for pattern in ROUTE_FILES:
        for file_path in repo_root.glob(pattern):
            files.add(file_path)
    return tuple(sorted(files))


def _extract_path(call: ast.Call) -> str:
    """Return the route path string from one router decorator call."""
    if (
        call.args
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
    ):
        return call.args[0].value
    for keyword in call.keywords:
        if keyword.arg != "path":
            continue
        if isinstance(keyword.value, ast.Constant) and isinstance(
            keyword.value.value, str
        ):
            return keyword.value.value
    return ""


def _extract_response_model(call: ast.Call) -> str:
    """Return the response_model expression text for one router decorator."""
    for keyword in call.keywords:
        if keyword.arg == "response_model":
            return ast.unparse(keyword.value)
    return ""


def _route_doc(node: ast.AST) -> RouteDoc | None:
    """Return one RouteDoc when the nested function defines a router decorator."""
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None

    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        func = decorator.func
        if not isinstance(func, ast.Attribute):
            continue
        if not isinstance(func.value, ast.Name) or func.value.id != "router":
            continue
        if func.attr not in _HTTP_METHODS:
            continue
        path = _extract_path(decorator)
        if path == "":
            continue
        return RouteDoc(
            method=func.attr.upper(),
            path=path,
            handler_name=node.name,
            response_model=_extract_response_model(decorator),
            summary=_first_line(ast.get_docstring(node)),
        )
    return None


def _module_doc(repo_root: Path, file_path: Path) -> ModuleDoc | None:
    """Parse one source file and return documented routes from register_routes."""
    module_rel = file_path.relative_to(repo_root).as_posix()
    tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=module_rel)

    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name != "register_routes":
            continue
        routes = [
            route for item in node.body if (route := _route_doc(item)) is not None
        ]
        if not routes:
            return None
        routes.sort(key=lambda route: (route.path, route.method, route.handler_name))
        return ModuleDoc(module_path=module_rel, routes=routes)
    return None


def _collect_modules(repo_root: Path) -> list[ModuleDoc]:
    """Collect all route-bearing modules under the configured source patterns."""
    modules: list[ModuleDoc] = []
    for file_path in _discover_route_files(repo_root):
        module = _module_doc(repo_root, file_path)
        if module is not None:
            modules.append(module)
    modules.sort(key=lambda module: module.module_path)
    return modules


def _load_metadata(path: Path) -> dict[str, RouteMetadata]:
    """Load and validate route-intent metadata from YAML."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("HTTP route metadata YAML root must be a mapping")

    metadata: dict[str, RouteMetadata] = {}
    for key, value in raw.items():
        route_path = str(key).strip()
        why = str(value).strip()
        if route_path == "":
            raise ValueError("HTTP route metadata keys must be non-empty")
        if why == "":
            raise ValueError(
                f"HTTP route metadata value is required for route '{route_path}'"
            )
        metadata[route_path] = RouteMetadata(why=why)
    return metadata


def _validate_route_metadata(
    *,
    modules: list[ModuleDoc],
    metadata: dict[str, RouteMetadata],
) -> None:
    """Fail when any discovered route lacks required intent metadata."""
    missing: list[str] = []
    for module in modules:
        for route in module.routes:
            if route.path not in metadata:
                missing.append(f"{route.method} {route.path} ({module.module_path})")
    if missing:
        joined = "\n- ".join(sorted(missing))
        raise ValueError(
            f"Missing HTTP route metadata entries for discovered routes:\n- {joined}"
        )


def _render_markdown(
    modules: list[ModuleDoc],
    *,
    metadata: dict[str, RouteMetadata],
) -> str:
    """Render deterministic Markdown for the collected HTTP route docs."""
    lines: list[str] = [DOC_TITLE, DOC_GENERATED_NOTE, ""]

    if not modules:
        lines.append(DOC_EMPTY_MESSAGE)
    else:
        for module in modules:
            lines.append(HR)
            lines.append(f"## `{module.module_path}`")
            for index, route in enumerate(module.routes):
                if index > 0:
                    lines.append("")
                lines.append(
                    f"`{route.method} {route.path}` &mdash; {metadata[route.path].why}"
                )
                lines.append(f"*Handler: `{route.handler_name}`*")
                if route.response_model:
                    lines.append(f"*Response: `{route.response_model}`*")
                if route.summary:
                    lines.append(f"*Summary: {route.summary}*")
                lines.append("")

    while lines and lines[-1] == "":
        lines.pop()
    lines.extend(["", "", HR, f"_End of {DOC_NAME}_", ""])
    return "\n".join(lines)


def main() -> int:
    """Generate or drift-check the Core HTTP API Markdown document."""
    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    output_path = repo_root / args.output
    metadata_path = repo_root / args.metadata

    try:
        modules = _collect_modules(repo_root)
        metadata = _load_metadata(metadata_path)
        _validate_route_metadata(modules=modules, metadata=metadata)
        rendered = _render_markdown(modules, metadata=metadata)
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to generate HTTP API docs: {exc}", file=sys.stderr)
        return 1

    if args.check:
        current = (
            output_path.read_text(encoding="utf-8") if output_path.exists() else ""
        )
        if current != rendered:
            print(CHECK_OUT_OF_DATE_MESSAGE, file=sys.stderr)
            return 1
        return 0

    output_path.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
