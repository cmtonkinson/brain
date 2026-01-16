"""Registry loader and query utilities."""

from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .registry_schema import (
    AutonomyLevel,
    EntrypointRuntime,
    RateLimit,
    SkillDefinition,
    SkillRegistry,
    SkillStatus,
)
from .registry_validation import RegistryIndex, load_json, load_yaml, validate_overlay_data, validate_registry_data

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChannelPolicy:
    allow: set[str]
    deny: set[str]


@dataclass(frozen=True)
class ActorPolicy:
    allow: set[str]
    deny: set[str]


@dataclass(frozen=True)
class SkillRuntimeEntry:
    definition: SkillDefinition
    status: SkillStatus
    autonomy: AutonomyLevel
    rate_limit: RateLimit | None
    channels: ChannelPolicy | None
    actors: ActorPolicy | None


@dataclass(frozen=True)
class SkillRegistryView:
    registry_version: str
    skills: list[SkillRuntimeEntry]


class SkillRegistryLoader:
    """Load the base registry and apply optional overlays."""

    def __init__(
        self,
        base_path: Path | None = None,
        overlay_paths: Iterable[Path] | None = None,
        capability_path: Path | None = None,
    ) -> None:
        self._base_path = base_path or Path("config/skill-registry.json")
        self._capability_path = capability_path or Path("config/capabilities.json")
        self._overlay_paths = list(overlay_paths) if overlay_paths is not None else [
            Path("config/skill-registry.local.yml"),
            Path("~/.config/brain/skill-registry.local.yml").expanduser(),
        ]
        self._cached_view: SkillRegistryView | None = None
        self._cached_mtimes: dict[Path, float] = {}

    def load(self) -> SkillRegistryView:
        view = self._load_registry()
        self._cached_view = view
        self._cached_mtimes = self._current_mtimes()
        return view

    def reload_if_changed(self) -> SkillRegistryView:
        if self._cached_view is None:
            return self.load()
        if self._cached_mtimes != self._current_mtimes():
            return self.load()
        return self._cached_view

    def list_skills(
        self,
        status: SkillStatus | None = None,
        capability: str | None = None,
    ) -> list[SkillRuntimeEntry]:
        view = self.reload_if_changed()
        skills = view.skills
        if status is not None:
            skills = [skill for skill in skills if skill.status == status]
        if capability is not None:
            skills = [
                skill for skill in skills if capability in skill.definition.capabilities
            ]
        return skills

    def get_skill(self, name: str, version: str | None = None) -> SkillRuntimeEntry:
        matches = [
            skill
            for skill in self.reload_if_changed().skills
            if skill.definition.name == name
        ]
        if version is not None:
            matches = [
                skill
                for skill in matches
                if skill.definition.version == version
            ]
        if not matches:
            raise KeyError(f"skill not found: {name}@{version or '*'}")
        if len(matches) > 1:
            raise ValueError(f"multiple skill versions found for {name}")
        return matches[0]

    def _current_mtimes(self) -> dict[Path, float]:
        mtimes: dict[Path, float] = {}
        paths = [self._base_path] + list(self._overlay_paths)
        for path in paths:
            if path.exists():
                mtimes[path] = path.stat().st_mtime
        return mtimes

    def _load_registry(self) -> SkillRegistryView:
        if not self._base_path.exists():
            raise FileNotFoundError(f"registry file not found: {self._base_path}")

        registry_data = load_json(self._base_path)
        capability_ids = _load_capability_ids(self._capability_path)
        registry_errors = validate_registry_data(registry_data, capability_ids)
        if registry_errors:
            raise ValueError("registry validation failed: " + "; ".join(registry_errors))

        registry = SkillRegistry.model_validate(registry_data)
        registry_index = RegistryIndex.from_registry(registry)
        overrides = _load_overrides(self._overlay_paths, registry_index)

        entries: list[SkillRuntimeEntry] = []
        for skill in registry.skills:
            entry = _apply_overrides(skill, overrides)
            if _should_skip_entry(entry):
                continue
            entries.append(entry)
        return SkillRegistryView(registry_version=registry.registry_version, skills=entries)


def _load_capability_ids(path: Path) -> set[str]:
    if not path.exists():
        raise FileNotFoundError(f"capability list not found: {path}")
    data = load_json(path)
    return {entry["id"] for entry in data.get("capabilities", [])}


def _load_overrides(
    overlay_paths: Iterable[Path],
    registry_index: RegistryIndex,
) -> list[dict[str, object]]:
    overrides: list[dict[str, object]] = []
    for overlay_path in overlay_paths:
        if not overlay_path.exists():
            continue
        overlay_data = load_yaml(overlay_path)
        overlay_errors = validate_overlay_data(overlay_data, registry_index)
        if overlay_errors:
            raise ValueError(
                f"overlay validation failed for {overlay_path}: "
                + "; ".join(overlay_errors)
            )
        overrides.extend(overlay_data.get("overrides", []))
    return overrides


def _apply_overrides(
    skill: SkillDefinition,
    overrides: Iterable[dict[str, object]],
) -> SkillRuntimeEntry:
    status = skill.status
    autonomy = skill.autonomy
    rate_limit = skill.rate_limit
    channels: ChannelPolicy | None = None
    actors: ActorPolicy | None = None

    for override in overrides:
        if override.get("name") != skill.name:
            continue
        override_version = override.get("version")
        if override_version and override_version != skill.version:
            continue

        if "status" in override:
            status = SkillStatus(override["status"])
        if "autonomy" in override:
            autonomy = AutonomyLevel(override["autonomy"])
        if "rate_limit" in override:
            rate_limit = RateLimit.model_validate(override["rate_limit"])
        if "channels" in override:
            channel_data = override["channels"]
            channels = ChannelPolicy(
                allow=set(channel_data.get("allow", [])),
                deny=set(channel_data.get("deny", [])),
            )
        if "actors" in override:
            actor_data = override["actors"]
            actors = ActorPolicy(
                allow=set(actor_data.get("allow", [])),
                deny=set(actor_data.get("deny", [])),
            )

    return SkillRuntimeEntry(
        definition=skill,
        status=status,
        autonomy=autonomy,
        rate_limit=rate_limit,
        channels=channels,
        actors=actors,
    )


def _should_skip_entry(entry: SkillRuntimeEntry) -> bool:
    if entry.status != SkillStatus.disabled:
        return False
    if entry.definition.entrypoint.runtime != EntrypointRuntime.python:
        return False
    module_name = entry.definition.entrypoint.module
    if not module_name:
        return True
    try:
        spec = importlib.util.find_spec(module_name)
    except ModuleNotFoundError:
        spec = None
    if spec is None and not _module_exists_locally(module_name):
        logger.warning(
            "Skipping disabled skill with missing entrypoint module: %s",
            entry.definition.name,
        )
        return True
    return False


def _module_exists_locally(module_name: str) -> bool:
    base_dir = Path(__file__).resolve().parents[1]
    module_path = base_dir / (module_name.replace(".", "/") + ".py")
    package_path = base_dir / module_name.replace(".", "/") / "__init__.py"
    return module_path.exists() or package_path.exists()
