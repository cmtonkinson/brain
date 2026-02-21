"""Generate Markdown docs for L1 public Python service interfaces.

The generator parses ``services/*/*/service.py`` files via AST and emits a
single deterministic Markdown file describing abstract public API surfaces.
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

SERVICE_FILE_GLOB = "services/*/*/service.py"
DEFAULT_OUTPUT = "docs/service-api.md"
DOC_TITLE = "# L1 Public Service API"
DOC_GENERATED_NOTE = (
    "This document is generated from `services/*/*/service.py`. Do not edit by hand."
)
DOC_EMPTY_MESSAGE = "No L1 service interfaces were found."
CHECK_OUT_OF_DATE_MESSAGE = "L1 API docs are out of date. Run: make docs-api"

_ENTITY_MODIFIERS = frozenset({"active", "default", "current", "all"})
_VERB_GROUPS: dict[str, tuple[int, int]] = {
    "insert": (0, 0),
    "put": (0, 1),
    "upsert": (0, 2),
    "get": (1, 0),
    "list": (1, 1),
    "search": (1, 2),
    "delete": (2, 0),
}
_UNKNOWN_VERB_ORDER = (3, 99)


@dataclass(frozen=True)
class MethodDoc:
    """One documented abstract API method."""

    name: str
    signature: str
    summary: str
    entity: str
    verb: str
    filter_part: str


@dataclass(frozen=True)
class ServiceDoc:
    """One documented L1 public service interface class."""

    class_name: str
    module_path: str
    summary: str
    methods: list[MethodDoc]


def _is_abstractmethod(node: ast.FunctionDef) -> bool:
    """Return true when a function has an ``@abstractmethod`` decorator."""
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == "abstractmethod":
            return True
        if isinstance(decorator, ast.Attribute) and decorator.attr == "abstractmethod":
            return True
    return False


def _format_arg(arg: ast.arg, default: ast.expr | None) -> str:
    """Format one function argument with type/default if present."""
    rendered = arg.arg
    if arg.annotation is not None:
        rendered = f"{rendered}: {ast.unparse(arg.annotation)}"
    if default is not None:
        rendered = f"{rendered} = {ast.unparse(default)}"
    return rendered


def _format_signature(method: ast.FunctionDef) -> str:
    """Render one normalized function signature string from AST."""
    args = method.args
    parts: list[str] = []

    positional = list(args.posonlyargs) + list(args.args)
    positional_defaults = [None] * (len(positional) - len(args.defaults)) + list(
        args.defaults
    )

    for idx, arg in enumerate(args.posonlyargs):
        parts.append(_format_arg(arg, positional_defaults[idx]))
    if args.posonlyargs:
        parts.append("/")

    pos_start = len(args.posonlyargs)
    for idx, arg in enumerate(args.args):
        parts.append(_format_arg(arg, positional_defaults[pos_start + idx]))

    if args.vararg is not None:
        rendered = f"*{_format_arg(args.vararg, None)}"
        parts.append(rendered)
    elif args.kwonlyargs:
        parts.append("*")

    for kw_arg, kw_default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        parts.append(_format_arg(kw_arg, kw_default))

    if args.kwarg is not None:
        parts.append(f"**{_format_arg(args.kwarg, None)}")

    signature = ", ".join(part for part in parts if part and part != "self")
    if method.returns is not None:
        return f"{method.name}({signature}) -> {ast.unparse(method.returns)}"
    return f"{method.name}({signature})"


def _first_line(docstring: str | None) -> str:
    """Extract first non-empty docstring line for concise summaries."""
    if not docstring:
        return ""
    for line in docstring.strip().splitlines():
        value = line.strip()
        if value:
            return value
    return ""


def _split_method_name(name: str) -> tuple[str, str, str]:
    """Split method name into ``(verb, entity, filter_part)`` for sorting."""
    tokens = [token for token in name.split("_") if token]
    if not tokens:
        return "", "", ""
    verb = tokens[0]
    remainder = tokens[1:]
    if not remainder:
        return verb, "", ""
    if "by" in remainder:
        by_index = remainder.index("by")
        entity_tokens = remainder[:by_index]
        filter_tokens = remainder[by_index + 1 :]
        entity = _normalize_entity_tokens(entity_tokens)
        return verb, entity, _join_tokens(filter_tokens)
    entity_tokens = list(remainder)
    filter_tokens = _pop_leading_modifiers(entity_tokens)
    entity = _normalize_entity_tokens(entity_tokens)
    filter_part = _join_tokens(remainder[1:])
    if filter_tokens:
        combined = [*filter_tokens, *([filter_part] if filter_part else [])]
        filter_part = _join_tokens(combined)
    return verb, entity, filter_part


def _join_tokens(tokens: list[str]) -> str:
    """Join string tokens with underscores."""
    return "_".join(tokens)


def _pop_leading_modifiers(tokens: list[str]) -> list[str]:
    """Pop and return leading modifier tokens while preserving order."""
    popped: list[str] = []
    while len(tokens) > 1 and tokens[0] in _ENTITY_MODIFIERS:
        popped.append(tokens.pop(0))
    return popped


def _normalize_entity_tokens(tokens: list[str]) -> str:
    """Collapse leading modifiers and return best-guess semantic entity token."""
    normalized = list(tokens)
    while len(normalized) > 1 and normalized[0] in _ENTITY_MODIFIERS:
        normalized.pop(0)
    if not normalized:
        return ""
    return normalized[0]


def _verb_order_key(verb: str) -> tuple[int, int, str]:
    """Return sorting key for the requested verb-group ordering."""
    group, rank = _VERB_GROUPS.get(verb, _UNKNOWN_VERB_ORDER)
    return group, rank, verb


def _method_sort_key(method: MethodDoc) -> tuple[object, ...]:
    """Sort by entity, then verb priority, then filter, then method name."""
    return (
        method.entity,
        *_verb_order_key(method.verb),
        method.filter_part,
        method.name,
    )


def _collect_services(repo_root: Path) -> list[ServiceDoc]:
    """Parse service interface files and collect abstract API docs."""
    services: list[ServiceDoc] = []
    for service_file in sorted(repo_root.glob(SERVICE_FILE_GLOB)):
        module_rel = service_file.relative_to(repo_root).as_posix()
        tree = ast.parse(service_file.read_text(encoding="utf-8"), filename=module_rel)

        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            methods: list[MethodDoc] = []
            for member in node.body:
                if not isinstance(member, ast.FunctionDef):
                    continue
                if not _is_abstractmethod(member):
                    continue
                verb, entity, filter_part = _split_method_name(member.name)
                methods.append(
                    MethodDoc(
                        name=member.name,
                        signature=_format_signature(member),
                        summary=_first_line(ast.get_docstring(member)),
                        entity=entity,
                        verb=verb,
                        filter_part=filter_part,
                    )
                )
            if not methods:
                continue
            methods.sort(key=_method_sort_key)
            services.append(
                ServiceDoc(
                    class_name=node.name,
                    module_path=module_rel,
                    summary=_first_line(ast.get_docstring(node)),
                    methods=methods,
                )
            )

    return services


def _render_markdown(services: list[ServiceDoc]) -> str:
    """Render deterministic API markdown from collected service docs."""
    lines: list[str] = [DOC_TITLE, "", DOC_GENERATED_NOTE, ""]

    if not services:
        lines.append(DOC_EMPTY_MESSAGE)
        lines.append("")
        return "\n".join(lines)

    for service in services:
        lines.append("---")
        lines.append("")
        lines.append(f"## `{service.class_name}`")
        lines.append("")
        lines.append(f"- Module: `{service.module_path}`")
        if service.summary:
            lines.append(f"- Summary: {service.summary}")
        lines.append("")
        for method in service.methods:
            lines.append(f"`{method.signature}`  ")
            lines.append(f"_{method.summary}_")
            lines.append("")
        lines.append("")

    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    """Parse command line arguments for generation/check modes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help="Path to generated markdown output.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if output file is not up to date.",
    )
    return parser.parse_args()


def main() -> int:
    """Generate docs file or check for drift."""
    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    output_path = (repo_root / args.output).resolve()

    services = _collect_services(repo_root)
    markdown = _render_markdown(services)
    if not markdown.endswith("\n"):
        markdown += "\n"

    if args.check:
        if not output_path.exists():
            print(f"Missing generated file: {output_path}", file=sys.stderr)
            return 1
        existing = output_path.read_text(encoding="utf-8")
        if existing != markdown:
            print(CHECK_OUT_OF_DATE_MESSAGE, file=sys.stderr)
            return 1
        print(f"L1 API docs are up to date: {output_path}")
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
