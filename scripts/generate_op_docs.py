"""Generate Markdown docs for registered op manifests."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

OP_ROOT = "ops"
DEFAULT_OUTPUT = "docs/ops.md"
DOC_NAME = "Op Catalog"
DOC_TITLE = f"# {DOC_NAME}"
HR = "------------------------------------------------------------------------"
DOC_GENERATED_NOTE = (
    "_This document is generated from `ops/**/op.json`. Do not edit by hand._"
)
DOC_EMPTY_MESSAGE = "No enabled ops were found."
CHECK_OUT_OF_DATE_MESSAGE = "Op docs are out of date. Run: make docs"

_GROUP_PIPELINE = "Pipeline Ops"
_GROUP_LOGIC = "Logic Ops"

_DIR_SERVICE_LABELS = {
    "cache": "Cache Service",
    "commitment": "Commitment Service",
    "delegation": "Delegation Service",
    "embedding": "Embedding Service",
    "execution": "Execution Service",
    "ingestion": "Ingestion Service",
    "job": "Job Service",
    "language": "Language Service",
    "object": "Object Service",
    "policy": "Policy Service",
    "recall": "Recall Service",
    "relay": "Relay Service",
    "utility": "Utility Service",
    "vault": "Vault Service",
}

_SERVICE_LABELS = {
    "service_cache": "Cache Service",
    "service_commitment": "Commitment Service",
    "service_delegation": "Delegation Service",
    "service_embedding": "Embedding Service",
    "service_execution": "Execution Service",
    "service_ingestion": "Ingestion Service",
    "service_job": "Job Service",
    "service_language": "Language Service",
    "service_object": "Object Service",
    "service_policy": "Policy Service",
    "service_recall": "Recall Service",
    "service_relay": "Relay Service",
    "service_utility": "Utility Service",
    "service_vault": "Vault Service",
}

_KIND_LABELS = {
    "logic": "Logic Op",
    "mcp": "MCP Op",
    "native": "Native Op",
    "pipeline": "Pipeline Op",
}


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


def _bootstrap_import_path(repo_root: Path) -> None:
    """Ensure the repository root is importable for project-local modules."""
    repo_root_text = str(repo_root)
    if repo_root_text not in sys.path:
        sys.path.insert(0, repo_root_text)


def _collect_manifests(repo_root: Path) -> tuple[object, ...]:
    """Discover enabled op manifests using the canonical registry path."""
    _bootstrap_import_path(repo_root)
    from services.effect.execution.registry import OpRegistry

    registry = OpRegistry()
    registry.discover(roots=(repo_root / OP_ROOT,))
    return registry.list_manifests()


def _manifest_path(manifest: object, repo_root: Path) -> Path | None:
    """Return the op.json path for one manifest, if resolvable."""
    op_id = getattr(manifest, "op_id", "")
    for path in (repo_root / OP_ROOT).rglob("op.json"):
        if path.parent.name == op_id:
            return path
    return None


def _service_group(manifest: object, repo_root: Path) -> str | None:
    """Return the service group label for a native op, inferred from directory."""
    path = _manifest_path(manifest, repo_root)
    if path is None:
        return None
    service_dir = path.parent.parent.name
    return _DIR_SERVICE_LABELS.get(service_dir) or _SERVICE_LABELS.get(service_dir)


def _tag_line(manifest: object) -> str:
    """Render the compact inline tag list for one op."""
    tags = [getattr(manifest, "kind"), getattr(manifest, "version")]
    tags.append(f"effect: {getattr(manifest, 'effect')}")
    tags.append(f"approval: {getattr(manifest, 'approval')}")
    return " ".join(f"`{tag}`" for tag in tags) + "  "


def _implementation_lines(manifest: object, repo_root: Path) -> list[str]:
    """Render one op's implementation summary lines."""
    kind = getattr(manifest, "kind")
    kind_label = _KIND_LABELS.get(kind, kind)
    call_target = getattr(manifest, "call_target", "")
    if call_target:
        if kind == "native":
            component_id, method_name = call_target.split(".", 1)
            service_label = _SERVICE_LABELS.get(component_id, component_id)
            return [f"{kind_label} over `{service_label} {method_name}()`  "]
        return [f"{kind_label}  "]

    if kind == "pipeline":
        lines = [f"{kind_label}:  "]
        for index, entry in enumerate(getattr(manifest, "pipeline"), start=1):
            step = _pipeline_step(entry)
            lines.append(f"{index}. `{step['op']}`{_pipeline_mapping_suffix(step)}  ")
        return lines

    return [f"{kind_label}  "]


def _pipeline_step(entry: object) -> dict[str, Any]:
    """Normalize one pipeline step to a mapping view."""
    if isinstance(entry, str):
        return {"op": entry, "input_mapping": {}}
    op_ref = getattr(entry, "op", "")
    input_mapping = getattr(entry, "input_mapping", {})
    return {
        "op": op_ref,
        "input_mapping": dict(input_mapping),
    }


def _pipeline_mapping_suffix(step: dict[str, Any]) -> str:
    """Render one optional compact mapping suffix for a pipeline step."""
    input_mapping = step["input_mapping"]
    if not input_mapping:
        return ""
    pairs = ", ".join(
        f"{consumer} <- {producer}"
        for consumer, producer in sorted(input_mapping.items())
    )
    return f" _({pairs})_"


def _render_schema_block(title: str, schema: dict[str, Any] | None) -> list[str]:
    """Render one Inputs/Outputs block from a canonical JSON Schema fragment."""
    if schema is None:
        return [f"**{title}:** None", ""]

    lines = [f"**{title}:**"]
    object_lines = _render_object_schema(schema)
    if object_lines:
        lines.extend(object_lines)
    else:
        lines.append(_render_value_line(schema))
    lines.append("")
    return lines


def _render_object_schema(schema: dict[str, Any]) -> list[str]:
    """Render object properties as one flat bullet list."""
    if schema.get("type") != "object":
        return []
    properties = schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        return []

    required = schema.get("required", [])
    required_set = (
        {value for value in required if isinstance(value, str)}
        if isinstance(required, list)
        else set()
    )
    lines: list[str] = []
    for name, field_schema in properties.items():
        if not isinstance(field_schema, dict):
            continue
        lines.append(_render_field_line(name, field_schema, name in required_set))
    return lines


def _render_field_line(
    name: str,
    schema: dict[str, Any],
    is_required: bool,
) -> str:
    """Render one schema property bullet."""
    meta = [_schema_label(schema)]
    if not is_required:
        meta.append("optional")
    if "default" in schema:
        meta.append(f"default={schema['default']!r}")

    line = f"- `{name}` _({', '.join(meta)})_"
    description = _description(schema)
    if description:
        line += f" {description}"
    return line


def _render_value_line(schema: dict[str, Any]) -> str:
    """Render one non-object schema as a single descriptive bullet."""
    line = f"- `{_schema_label(schema)}`"
    description = _description(schema)
    if description:
        line += f": {description}"
    return line


def _description(schema: dict[str, Any]) -> str:
    """Return one schema description when present."""
    description = schema.get("description")
    if isinstance(description, str):
        return description
    return ""


def _schema_label(schema: dict[str, Any]) -> str:
    """Return a compact human-readable type label for one schema fragment."""
    any_of = schema.get("anyOf")
    if isinstance(any_of, list) and any_of:
        return " | ".join(
            _schema_label(option) for option in any_of if isinstance(option, dict)
        )

    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        return " | ".join(str(value) for value in schema_type)
    if schema_type == "array":
        items = schema.get("items")
        if isinstance(items, dict):
            return f"array[{_schema_label(items)}]"
        return "array"
    if isinstance(schema_type, str) and schema_type:
        return schema_type
    return "any"


def _render_op(manifest: object, repo_root: Path, lines: list[str]) -> None:
    """Append one op's markdown block to lines."""
    lines.append(f"### `{getattr(manifest, 'op_id')}`")
    lines.append(f"{getattr(manifest, 'summary')}  ")
    lines.append(_tag_line(manifest))
    lines.extend(_implementation_lines(manifest, repo_root))
    lines.append("")
    lines.extend(_render_schema_block("Inputs", getattr(manifest, "input_schema")))
    lines.extend(_render_schema_block("Outputs", getattr(manifest, "output_schema")))


def _render_markdown(manifests: tuple[object, ...], repo_root: Path) -> str:
    """Render deterministic op catalog markdown."""
    lines: list[str] = [DOC_TITLE, DOC_GENERATED_NOTE, ""]
    if not manifests:
        lines.append(DOC_EMPTY_MESSAGE)
    else:
        service_groups: dict[str, list[object]] = {}
        pipeline_ops: list[object] = []
        logic_ops: list[object] = []

        for manifest in manifests:
            kind = getattr(manifest, "kind", "")
            if kind == "pipeline":
                pipeline_ops.append(manifest)
            elif kind == "logic":
                logic_ops.append(manifest)
            else:
                label = _service_group(manifest, repo_root)
                if label is None:
                    raise ValueError(
                        f"cannot determine service group for native op "
                        f"{getattr(manifest, 'op_id', '<unknown>')}"
                    )
                service_groups.setdefault(label, []).append(manifest)

        for service_label in sorted(service_groups):
            lines.append(HR)
            lines.append(f"## `{service_label}`")
            for manifest in sorted(
                service_groups[service_label],
                key=lambda m: getattr(m, "op_id"),
            ):
                _render_op(manifest, repo_root, lines)

        if pipeline_ops:
            lines.append(HR)
            lines.append(f"## `{_GROUP_PIPELINE}`")
            for manifest in sorted(pipeline_ops, key=lambda m: getattr(m, "op_id")):
                _render_op(manifest, repo_root, lines)

        if logic_ops:
            lines.append(HR)
            lines.append(f"## `{_GROUP_LOGIC}`")
            for manifest in sorted(logic_ops, key=lambda m: getattr(m, "op_id")):
                _render_op(manifest, repo_root, lines)

    while lines and lines[-1] == "":
        lines.pop()
    lines.extend(["", "", HR, f"_End of {DOC_NAME}_", ""])
    return "\n".join(lines)


def main() -> int:
    """Generate docs file or check for drift."""
    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    output_path = (repo_root / args.output).resolve()

    manifests = _collect_manifests(repo_root)
    markdown = _render_markdown(manifests, repo_root)
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
        print(f"Op docs are up to date: {output_path}")
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
