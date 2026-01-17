"""Validation utilities for skill and op registries and overlays."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from .pipeline_validation import PipelineValidationContext, validate_pipeline_skill
from .registry_schema import (
    AutonomyLevel,
    CallTargetKind,
    OpRegistry,
    RateLimit,
    SkillKind,
    SkillRegistry,
)


@dataclass(frozen=True)
class RegistryIndex:
    """Index for resolving registry entries by name and version."""

    names_to_versions: dict[str, set[str]]

    @classmethod
    def from_registry(cls, registry: SkillRegistry) -> "RegistryIndex":
        """Build an index from a skill registry."""
        names_to_versions: dict[str, set[str]] = {}
        for skill in registry.skills:
            names_to_versions.setdefault(skill.name, set()).add(skill.version)
        return cls(names_to_versions)

    @classmethod
    def from_op_registry(cls, registry: OpRegistry) -> "RegistryIndex":
        """Build an index from an op registry."""
        names_to_versions: dict[str, set[str]] = {}
        for op_entry in registry.ops:
            names_to_versions.setdefault(op_entry.name, set()).add(op_entry.version)
        return cls(names_to_versions)

    def has_skill(self, name: str, version: str | None = None) -> bool:
        """Return True if the registry contains the named skill/version."""
        versions = self.names_to_versions.get(name)
        if not versions:
            return False
        if version is None:
            return True
        return version in versions


def load_json(path: Path) -> dict[str, Any]:
    """Load JSON data from disk."""
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml(path: Path) -> dict[str, Any]:
    """Load YAML data from disk."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_capability_ids(path: Path) -> set[str]:
    """Load capability IDs from a capability registry file."""
    data = load_json(path)
    return {entry["id"] for entry in data.get("capabilities", [])}


def validate_registry_data(
    data: dict[str, Any],
    capability_ids: Iterable[str],
    op_index: RegistryIndex | None = None,
    op_registry: OpRegistry | None = None,
) -> list[str]:
    """Validate a skill registry payload."""
    errors: list[str] = []
    try:
        registry = SkillRegistry.model_validate(data)
    except Exception as exc:  # pragma: no cover - specific error covered in tests
        return [f"schema error: {exc}"]

    seen: set[tuple[str, str]] = set()
    for skill in registry.skills:
        key = (skill.name, skill.version)
        if key in seen:
            errors.append(f"duplicate skill entry for {skill.name}@{skill.version}")
        else:
            seen.add(key)

        for cap_id in skill.capabilities + skill.side_effects:
            if cap_id not in capability_ids:
                errors.append(f"unknown capability: {cap_id} (skill {skill.name})")

        errors.extend(
            _validate_skill_call_targets(
                skill, registry, op_index, require_ops=op_index is not None
            )
        )

        if skill.kind == SkillKind.pipeline and op_registry is not None:
            context = PipelineValidationContext(
                skills_by_key={(entry.name, entry.version): entry for entry in registry.skills},
                ops_by_key={(entry.name, entry.version): entry for entry in op_registry.ops},
            )
            pipeline_errors, _ = validate_pipeline_skill(skill, context)
            errors.extend(pipeline_errors)

    return errors


def validate_registry_file(
    registry_path: Path,
    capabilities_path: Path,
    op_registry_path: Path | None = None,
) -> list[str]:
    """Validate a skill registry file against capabilities and ops."""
    data = load_json(registry_path)
    capability_ids = load_capability_ids(capabilities_path)
    op_index = None
    op_registry = None
    if op_registry_path is not None and op_registry_path.exists():
        op_data = load_json(op_registry_path)
        op_registry = OpRegistry.model_validate(op_data)
        op_index = RegistryIndex.from_op_registry(op_registry)
    return validate_registry_data(
        data,
        capability_ids,
        op_index=op_index,
        op_registry=op_registry,
    )


def validate_op_registry_data(data: dict[str, Any], capability_ids: Iterable[str]) -> list[str]:
    """Validate an op registry payload."""
    errors: list[str] = []
    try:
        registry = OpRegistry.model_validate(data)
    except Exception as exc:  # pragma: no cover - specific error covered in tests
        return [f"schema error: {exc}"]

    seen: set[tuple[str, str]] = set()
    for op_entry in registry.ops:
        key = (op_entry.name, op_entry.version)
        if key in seen:
            errors.append(f"duplicate op entry for {op_entry.name}@{op_entry.version}")
        else:
            seen.add(key)

        for cap_id in op_entry.capabilities + op_entry.side_effects:
            if cap_id not in capability_ids:
                errors.append(f"unknown capability: {cap_id} (op {op_entry.name})")

    return errors


def validate_op_registry_file(registry_path: Path, capabilities_path: Path) -> list[str]:
    """Validate an op registry file against capabilities."""
    data = load_json(registry_path)
    capability_ids = load_capability_ids(capabilities_path)
    return validate_op_registry_data(data, capability_ids)


def _validate_overlay_entry(entry: dict[str, Any]) -> list[str]:
    """Validate the schema of a single overlay entry."""
    errors: list[str] = []
    allowed_keys = {
        "name",
        "version",
        "status",
        "autonomy",
        "rate_limit",
        "channels",
        "actors",
    }
    unexpected = set(entry.keys()) - allowed_keys
    if unexpected:
        errors.append(f"unexpected overlay fields: {sorted(unexpected)}")

    if "status" in entry and entry["status"] not in {"enabled", "disabled"}:
        errors.append("overlay status must be enabled or disabled")

    if "autonomy" in entry:
        try:
            AutonomyLevel(entry["autonomy"])
        except Exception:
            errors.append("overlay autonomy must be one of L0, L1, L2, L3")

    if "rate_limit" in entry:
        try:
            RateLimit.model_validate(entry["rate_limit"])
        except Exception as exc:
            errors.append(f"invalid rate_limit: {exc}")

    if "channels" in entry:
        channels = entry["channels"]
        if not isinstance(channels, dict):
            errors.append("channels must be a mapping")
        else:
            channel_keys = set(channels.keys())
            if not channel_keys.issubset({"allow", "deny"}):
                errors.append("channels only supports allow/deny lists")
            for key in channel_keys:
                if not isinstance(channels[key], list):
                    errors.append(f"channels.{key} must be a list")

    if "actors" in entry:
        actors = entry["actors"]
        if not isinstance(actors, dict):
            errors.append("actors must be a mapping")
        else:
            actor_keys = set(actors.keys())
            if not actor_keys.issubset({"allow", "deny"}):
                errors.append("actors only supports allow/deny lists")
            for key in actor_keys:
                if not isinstance(actors[key], list):
                    errors.append(f"actors.{key} must be a list")

    if "name" not in entry:
        errors.append("overlay entry missing name")

    return errors


def validate_overlay_data(
    data: dict[str, Any],
    registry_index: RegistryIndex | None = None,
    *,
    entry_label: str = "skill",
) -> list[str]:
    """Validate overlay data against a registry index."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["overlay must be a mapping"]

    if "overlay_version" not in data:
        errors.append("overlay missing overlay_version")

    overrides = data.get("overrides")
    if not isinstance(overrides, list):
        return errors + ["overlay overrides must be a list"]

    for entry in overrides:
        if not isinstance(entry, dict):
            errors.append("overlay entries must be mappings")
            continue
        errors.extend(_validate_overlay_entry(entry))

        name = entry.get("name")
        version = entry.get("version")
        if registry_index and name:
            if not registry_index.has_skill(name, version):
                if version:
                    errors.append(f"unknown {entry_label} {name}@{version} in overlay")
                else:
                    errors.append(f"unknown {entry_label} {name} in overlay")

    return errors


def validate_overlay_file(
    overlay_path: Path,
    registry_index: RegistryIndex | None = None,
    *,
    entry_label: str = "skill",
) -> list[str]:
    """Validate an overlay file against a registry index."""
    data = load_yaml(overlay_path)
    return validate_overlay_data(data, registry_index, entry_label=entry_label)


def _validate_skill_call_targets(
    skill: Any,
    registry: SkillRegistry,
    op_index: RegistryIndex | None,
    *,
    require_ops: bool,
) -> list[str]:
    """Validate that skill call targets resolve to known skills or ops."""
    errors: list[str] = []
    skill_index = RegistryIndex.from_registry(registry)

    if skill.kind == SkillKind.logic:
        targets = skill.call_targets
    else:
        targets = [step.target for step in skill.steps]

    for target in targets:
        if target.kind == CallTargetKind.skill:
            if not skill_index.has_skill(target.name, target.version):
                if target.version:
                    errors.append(
                        f"unknown skill target {target.name}@{target.version} in {skill.name}"
                    )
                else:
                    errors.append(f"unknown skill target {target.name} in {skill.name}")
        else:
            if op_index is None:
                if require_ops:
                    errors.append(f"missing op registry for target {target.name} in {skill.name}")
                continue
            if not op_index.has_skill(target.name, target.version):
                if target.version:
                    errors.append(
                        f"unknown op target {target.name}@{target.version} in {skill.name}"
                    )
                else:
                    errors.append(f"unknown op target {target.name} in {skill.name}")

    return errors
