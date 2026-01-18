"""List policies with precedence order and report conflicts."""

from __future__ import annotations

import argparse
import json
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

PRECEDENCE_ORDER = [
    "base_registry",
    "overlay_1",
    "overlay_2",
    "overlay_3",
    "overlay_4",
]


@dataclass(frozen=True)
class OverlayEntry:
    """Overlay entry with source metadata."""

    source: str
    data: dict[str, Any]


def _load_overlays(paths: Iterable[Path]) -> list[OverlayEntry]:
    """Load overlays and attach source metadata."""
    entries: list[OverlayEntry] = []
    for path in paths:
        if not path.exists():
            continue
        data = load_yaml(path)
        for override in data.get("overrides", []):
            entries.append(OverlayEntry(source=str(path), data=override))
    return entries


def _collect_override_values(
    overrides: Iterable[OverlayEntry], name: str, version: str
) -> dict[str, set[str]]:
    """Collect distinct override values per field for conflict detection."""
    fields: dict[str, set[str]] = {
        "status": set(),
        "autonomy": set(),
        "rate_limit": set(),
    }
    for override in overrides:
        if override.data.get("name") != name:
            continue
        override_version = override.data.get("version")
        if override_version and override_version != version:
            continue
        for field in list(fields.keys()):
            if field in override.data:
                fields[field].add(str(override.data[field]))
    return fields


def _overlay_channel_actor_conflicts(
    overrides: Iterable[OverlayEntry],
    *,
    name: str,
    version: str,
    label: str,
) -> list[dict[str, Any]]:
    """Detect allow/deny overlaps in overlay channel/actor policies."""
    conflicts: list[dict[str, Any]] = []
    for override in overrides:
        if override.data.get("name") != name:
            continue
        override_version = override.data.get("version")
        if override_version and override_version != version:
            continue
        channels = override.data.get("channels") or {}
        actors = override.data.get("actors") or {}
        channel_overlap = set(channels.get("allow", [])) & set(channels.get("deny", []))
        if channel_overlap:
            conflicts.append(
                {
                    "policy_id": f"{label}:{name}@{version}",
                    "type": "channel_allow_deny_overlap",
                    "details": {"overlap": sorted(channel_overlap), "source": override.source},
                }
            )
        actor_overlap = set(actors.get("allow", [])) & set(actors.get("deny", []))
        if actor_overlap:
            conflicts.append(
                {
                    "policy_id": f"{label}:{name}@{version}",
                    "type": "actor_allow_deny_overlap",
                    "details": {"overlap": sorted(actor_overlap), "source": override.source},
                }
            )
    return conflicts


def _build_policy_entry(entry: dict[str, Any], label: str) -> dict[str, Any]:
    """Build a normalized policy entry for listing."""
    return {
        "id": f"{label}:{entry['name']}@{entry['version']}",
        "autonomy": getattr(entry.get("autonomy"), "value", entry.get("autonomy")),
        "policy_tags": entry.get("policy_tags", []),
        "channels": entry.get("channels") or {},
        "actors": entry.get("actors") or {},
    }


def generate_conflict_report(
    *,
    skill_registry_path: Path,
    op_registry_path: Path,
    capabilities_path: Path,
    skill_overlays: list[Path],
    op_overlays: list[Path],
) -> dict[str, Any]:
    """Generate policy listing with conflict detection results."""
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

    skill_overrides = _load_overlays(skill_overlays)
    op_overrides = _load_overlays(op_overlays)

    conflicts: list[dict[str, Any]] = []
    policies: list[dict[str, Any]] = []

    for skill in skill_registry.skills:
        entry = skill.model_dump()
        policies.append(_build_policy_entry(entry, "skill"))
        channels = entry.get("channels") or {}
        actors = entry.get("actors") or {}
        channel_overlap = set(channels.get("allow", [])) & set(channels.get("deny", []))
        if channel_overlap:
            conflicts.append(
                {
                    "policy_id": f"skill:{entry['name']}@{entry['version']}",
                    "type": "channel_allow_deny_overlap",
                    "details": sorted(channel_overlap),
                }
            )
        actor_overlap = set(actors.get("allow", [])) & set(actors.get("deny", []))
        if actor_overlap:
            conflicts.append(
                {
                    "policy_id": f"skill:{entry['name']}@{entry['version']}",
                    "type": "actor_allow_deny_overlap",
                    "details": sorted(actor_overlap),
                }
            )
        conflicts.extend(
            _overlay_channel_actor_conflicts(
                skill_overrides,
                name=entry["name"],
                version=entry["version"],
                label="skill",
            )
        )
        override_values = _collect_override_values(skill_overrides, entry["name"], entry["version"])
        for field, values in override_values.items():
            if len(values) > 1:
                conflicts.append(
                    {
                        "policy_id": f"skill:{entry['name']}@{entry['version']}",
                        "type": "conflicting_overrides",
                        "details": {"field": field, "values": sorted(values)},
                    }
                )

    for op_entry in op_registry.ops:
        entry = op_entry.model_dump()
        policies.append(_build_policy_entry(entry, "op"))
        channels = entry.get("channels") or {}
        actors = entry.get("actors") or {}
        channel_overlap = set(channels.get("allow", [])) & set(channels.get("deny", []))
        if channel_overlap:
            conflicts.append(
                {
                    "policy_id": f"op:{entry['name']}@{entry['version']}",
                    "type": "channel_allow_deny_overlap",
                    "details": sorted(channel_overlap),
                }
            )
        actor_overlap = set(actors.get("allow", [])) & set(actors.get("deny", []))
        if actor_overlap:
            conflicts.append(
                {
                    "policy_id": f"op:{entry['name']}@{entry['version']}",
                    "type": "actor_allow_deny_overlap",
                    "details": sorted(actor_overlap),
                }
            )
        conflicts.extend(
            _overlay_channel_actor_conflicts(
                op_overrides,
                name=entry["name"],
                version=entry["version"],
                label="op",
            )
        )
        override_values = _collect_override_values(op_overrides, entry["name"], entry["version"])
        for field, values in override_values.items():
            if len(values) > 1:
                conflicts.append(
                    {
                        "policy_id": f"op:{entry['name']}@{entry['version']}",
                        "type": "conflicting_overrides",
                        "details": {"field": field, "values": sorted(values)},
                    }
                )

    return {
        "precedence_order": PRECEDENCE_ORDER,
        "policies": policies,
        "conflicts": conflicts,
    }


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for conflict reporting."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-registry", default="config/skill-registry.json")
    parser.add_argument("--op-registry", default="config/op-registry.json")
    parser.add_argument("--capabilities", default="config/capabilities.json")
    return parser.parse_args()


def main() -> None:
    """Generate conflict report and print JSON output."""
    args = _parse_args()
    skill_overlays = [
        Path("config/skill-registry.local.yml"),
        Path("~/.config/brain/skill-registry.local.yml").expanduser(),
    ]
    op_overlays = [
        Path("config/op-registry.local.yml"),
        Path("~/.config/brain/op-registry.local.yml").expanduser(),
    ]
    report = generate_conflict_report(
        skill_registry_path=Path(args.skill_registry),
        op_registry_path=Path(args.op_registry),
        capabilities_path=Path(args.capabilities),
        skill_overlays=skill_overlays,
        op_overlays=op_overlays,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
