"""Generate Markdown docs for registered capability manifests."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

CAPABILITY_ROOT = "capabilities"
DEFAULT_OUTPUT = "docs/capabilities.md"
DOC_NAME = "Capability Catalog"
DOC_TITLE = f"# {DOC_NAME}"
HR = "------------------------------------------------------------------------"
DOC_GENERATED_NOTE = (
    "_This document is generated from `capabilities/**/capability.json`. "
    "Do not edit by hand._"
)
DOC_EMPTY_MESSAGE = "No enabled capabilities were found."
CHECK_OUT_OF_DATE_MESSAGE = "Capability docs are out of date. Run: make docs"

_GROUP_FALLBACK = "Capability Engine Service"
_SERVICE_LABELS = {
    "service_attention_router": "Attention Router Service",
    "service_cache_authority": "Cache Authority Service",
    "service_embedding_authority": "Embedding Authority Service",
    "service_language_model": "Language Model Service",
    "service_memory_authority": "Memory Authority Service",
    "service_object_authority": "Object Authority Service",
    "service_policy_service": "Policy Service",
    "service_switchboard": "Switchboard Service",
    "service_utility_service": "Utility Service",
    "service_vault_authority": "Vault Authority Service",
}
_KIND_LABELS = {
    "logic_skill": "Logic Skill",
    "mcp_op": "MCP Op",
    "native_op": "Native Op",
    "pipeline_skill": "Pipeline Skill",
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
    """Discover enabled capability manifests using the canonical registry path."""
    _bootstrap_import_path(repo_root)
    from services.action.capability_engine.registry import CapabilityRegistry

    registry = CapabilityRegistry()
    registry.discover(root=repo_root / CAPABILITY_ROOT)
    return registry.list_manifests()


def _service_label(manifest: object) -> str:
    """Return the human-readable service group for one capability."""
    if getattr(manifest, "kind", "") == "native_op" and hasattr(
        manifest, "call_target"
    ):
        component_id, _method_name = getattr(manifest, "call_target").split(".", 1)
        return _SERVICE_LABELS.get(component_id, component_id)
    return _GROUP_FALLBACK


def _tag_line(manifest: object) -> str:
    """Render the compact inline tag list for one capability."""
    tags = [getattr(manifest, "kind"), getattr(manifest, "version")]
    if getattr(manifest, "requires_approval"):
        tags.append("approval: required")
    autonomy = getattr(manifest, "autonomy")
    if autonomy >= 1:
        tags.append(f"autonomy: {autonomy}")
    return " ".join(f"`{tag}`" for tag in tags)


def _implementation_lines(manifest: object) -> list[str]:
    """Render one capability's implementation summary lines."""
    kind = getattr(manifest, "kind")
    kind_label = _KIND_LABELS.get(kind, kind)
    call_target = getattr(manifest, "call_target", "")
    if call_target:
        if kind == "native_op":
            component_id, method_name = call_target.split(".", 1)
            service_label = _SERVICE_LABELS.get(component_id, component_id)
            return [f"{kind_label} over `{service_label} {method_name}()`"]
        return [kind_label]

    if kind == "pipeline_skill":
        lines = [f"{kind_label} over:"]
        for index, entry in enumerate(getattr(manifest, "pipeline"), start=1):
            step = _pipeline_step(entry)
            lines.append(
                f"{index}. `{step['capability']}`{_pipeline_mapping_suffix(step)}"
            )
        return lines

    return [f"{kind_label} executed by `{_GROUP_FALLBACK}`"]


def _pipeline_step(entry: object) -> dict[str, Any]:
    """Normalize one pipeline step to a mapping view."""
    if isinstance(entry, str):
        return {"capability": entry, "input_mapping": {}}
    capability = getattr(entry, "capability", "")
    input_mapping = getattr(entry, "input_mapping", {})
    return {
        "capability": capability,
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


def _render_markdown(manifests: tuple[object, ...]) -> str:
    """Render deterministic capability catalog markdown."""
    lines: list[str] = [DOC_TITLE, DOC_GENERATED_NOTE, ""]
    if not manifests:
        lines.append(DOC_EMPTY_MESSAGE)
        lines.append("")
        lines.append(HR)
        lines.append(f"_End of {DOC_NAME}_")
        lines.append("")
        return "\n".join(lines)

    grouped: dict[str, list[object]] = {}
    for manifest in manifests:
        grouped.setdefault(_service_label(manifest), []).append(manifest)

    for service_label in sorted(grouped):
        lines.append(HR)
        lines.append(f"## `{service_label}`")
        manifests_for_service = sorted(
            grouped[service_label],
            key=lambda item: item.capability_id,
        )
        for manifest in manifests_for_service:
            lines.append(
                f"### `{getattr(manifest, 'capability_id')}` - {getattr(manifest, 'summary')}"
            )
            lines.append(_tag_line(manifest))
            lines.extend(_implementation_lines(manifest))
            lines.append("")
            lines.extend(
                _render_schema_block("Inputs", getattr(manifest, "input_schema"))
            )
            lines.extend(
                _render_schema_block("Outputs", getattr(manifest, "output_schema"))
            )

    lines.append(HR)
    lines.append(f"_End of {DOC_NAME}_")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    """Generate docs file or check for drift."""
    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    output_path = (repo_root / args.output).resolve()

    manifests = _collect_manifests(repo_root)
    markdown = _render_markdown(manifests)
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
        print(f"Capability docs are up to date: {output_path}")
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
