"""Validation utilities for skill registries and overlays."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from .registry_schema import AutonomyLevel, RateLimit, SkillRegistry


@dataclass(frozen=True)
class RegistryIndex:
    names_to_versions: dict[str, set[str]]

    @classmethod
    def from_registry(cls, registry: SkillRegistry) -> "RegistryIndex":
        names_to_versions: dict[str, set[str]] = {}
        for skill in registry.skills:
            names_to_versions.setdefault(skill.name, set()).add(skill.version)
        return cls(names_to_versions)

    def has_skill(self, name: str, version: str | None = None) -> bool:
        versions = self.names_to_versions.get(name)
        if not versions:
            return False
        if version is None:
            return True
        return version in versions


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_capability_ids(path: Path) -> set[str]:
    data = load_json(path)
    return {entry["id"] for entry in data.get("capabilities", [])}


def validate_registry_data(data: dict[str, Any], capability_ids: Iterable[str]) -> list[str]:
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

    return errors


def validate_registry_file(registry_path: Path, capabilities_path: Path) -> list[str]:
    data = load_json(registry_path)
    capability_ids = load_capability_ids(capabilities_path)
    return validate_registry_data(data, capability_ids)


def _validate_overlay_entry(entry: dict[str, Any]) -> list[str]:
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
) -> list[str]:
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
                    errors.append(f"unknown skill {name}@{version} in overlay")
                else:
                    errors.append(f"unknown skill {name} in overlay")

    return errors


def validate_overlay_file(
    overlay_path: Path,
    registry_index: RegistryIndex | None = None,
) -> list[str]:
    data = load_yaml(overlay_path)
    return validate_overlay_data(data, registry_index)
