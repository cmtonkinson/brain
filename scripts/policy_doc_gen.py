"""Generate human-readable policy documentation from registry data."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from skills.registry_schema import OpRegistry, SkillRegistry
from skills.registry_validation import (
    RegistryIndex,
    load_json,
    load_yaml,
    validate_op_registry_file,
    validate_overlay_file,
    validate_registry_file,
)


@dataclass(frozen=True)
class OverlayEntry:
    """Overlay entry with source information."""

    source: str
    data: dict[str, Any]


def _load_overlays(paths: Iterable[Path], entry_label: str) -> list[OverlayEntry]:
    """Load overlays from disk and attach source metadata."""
    overlays: list[OverlayEntry] = []
    for path in paths:
        if not path.exists():
            continue
        data = load_yaml(path)
        overrides = data.get("overrides", [])
        for override in overrides:
            overlays.append(OverlayEntry(source=str(path), data=override))
    return overlays


def _apply_overrides(
    base: dict[str, Any],
    overrides: Iterable[OverlayEntry],
    *,
    name: str,
    version: str,
) -> tuple[dict[str, Any], list[str]]:
    """Apply overlays in order and return updated policy fields and sources."""
    fields = {
        "status": base.get("status"),
        "autonomy": base.get("autonomy"),
        "rate_limit": base.get("rate_limit"),
        "channels": base.get("channels"),
        "actors": base.get("actors"),
    }
    sources: list[str] = []
    for override in overrides:
        if override.data.get("name") != name:
            continue
        override_version = override.data.get("version")
        if override_version and override_version != version:
            continue
        sources.append(override.source)
        for key in fields:
            if key in override.data:
                fields[key] = override.data[key]
    return fields, sources


def _render_entry(
    label: str,
    entry: dict[str, Any],
    overrides: Iterable[OverlayEntry],
) -> str:
    """Render a single skill/op entry into markdown."""

    def _format_value(value: Any) -> str:
        """Return a display-friendly value for enums and scalars."""
        if value is None:
            return ""
        return getattr(value, "value", value)

    name = entry["name"]
    version = entry["version"]
    fields, sources = _apply_overrides(entry, overrides, name=name, version=version)
    channels = fields.get("channels") or {}
    actors = fields.get("actors") or {}
    rate_limit = fields.get("rate_limit") or {}
    rationale = "registry default"
    if entry.get("policy_tags"):
        rationale = f"policy_tags({', '.join(entry.get('policy_tags', []))})"
    if sources:
        rationale = f"overlay override from {', '.join(sources)}"
    lines = [
        f"### {label}:{name}@{version}",
        f"- status: {_format_value(fields.get('status'))}",
        f"- autonomy: {_format_value(fields.get('autonomy'))}",
        f"- policy_tags: {', '.join(entry.get('policy_tags', []))}",
        f"- capabilities: {', '.join(entry.get('capabilities', []))}",
        f"- side_effects: {', '.join(entry.get('side_effects', []))}",
        f"- channels.allow: {', '.join(channels.get('allow', []))}",
        f"- channels.deny: {', '.join(channels.get('deny', []))}",
        f"- actors.allow: {', '.join(actors.get('allow', []))}",
        f"- actors.deny: {', '.join(actors.get('deny', []))}",
        f"- rate_limit.max_per_minute: {rate_limit.get('max_per_minute')}",
        f"- precedence_sources: {', '.join(sources) if sources else 'registry'}",
        f"- rationale: {rationale}",
    ]
    return "\n".join(lines)


def generate_policy_docs(
    skill_registry_path: Path,
    op_registry_path: Path,
    capabilities_path: Path,
    skill_overlays: Iterable[Path],
    op_overlays: Iterable[Path],
) -> str:
    """Generate policy documentation from registry and overlay data."""
    skill_errors = validate_registry_file(skill_registry_path, capabilities_path, op_registry_path)
    if skill_errors:
        raise ValueError("skill registry validation failed: " + "; ".join(skill_errors))
    op_errors = validate_op_registry_file(op_registry_path, capabilities_path)
    if op_errors:
        raise ValueError("op registry validation failed: " + "; ".join(op_errors))

    skill_registry = SkillRegistry.model_validate(load_json(skill_registry_path))
    op_registry = OpRegistry.model_validate(load_json(op_registry_path))

    skill_index = RegistryIndex.from_registry(skill_registry)
    op_index = RegistryIndex.from_op_registry(op_registry)

    for overlay_path in skill_overlays:
        if overlay_path.exists():
            overlay_errors = validate_overlay_file(overlay_path, skill_index, entry_label="skill")
            if overlay_errors:
                raise ValueError(
                    f"skill overlay validation failed for {overlay_path}: "
                    + "; ".join(overlay_errors)
                )

    for overlay_path in op_overlays:
        if overlay_path.exists():
            overlay_errors = validate_overlay_file(overlay_path, op_index, entry_label="op")
            if overlay_errors:
                raise ValueError(
                    f"op overlay validation failed for {overlay_path}: " + "; ".join(overlay_errors)
                )

    skill_overlay_entries = _load_overlays(skill_overlays, "skill")
    op_overlay_entries = _load_overlays(op_overlays, "op")

    lines = [
        "# Policy Documentation",
        "",
        "## Precedence Order",
        "1) Base registries",
        "2) Overlays in canonical order (later overrides earlier)",
        "",
        "## Skills",
    ]
    for skill in skill_registry.skills:
        lines.append(_render_entry("skill", skill.model_dump(), skill_overlay_entries))
        lines.append("")

    lines.append("## Ops")
    for op_entry in op_registry.ops:
        lines.append(_render_entry("op", op_entry.model_dump(), op_overlay_entries))
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for documentation generation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skill-registry",
        default="config/skill-registry.json",
        help="Path to the skill registry JSON file.",
    )
    parser.add_argument(
        "--op-registry",
        default="config/op-registry.json",
        help="Path to the op registry JSON file.",
    )
    parser.add_argument(
        "--capabilities",
        default="config/capabilities.json",
        help="Path to the capabilities registry JSON file.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional output path for generated docs (stdout when omitted).",
    )
    return parser.parse_args()


def main() -> None:
    """Generate policy documentation or raise on validation errors."""
    args = _parse_args()
    skill_overlays = [
        Path("config/skill-registry.local.yml"),
        Path("~/.config/brain/skill-registry.local.yml").expanduser(),
    ]
    op_overlays = [
        Path("config/op-registry.local.yml"),
        Path("~/.config/brain/op-registry.local.yml").expanduser(),
    ]
    output = generate_policy_docs(
        Path(args.skill_registry),
        Path(args.op_registry),
        Path(args.capabilities),
        skill_overlays,
        op_overlays,
    )
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
