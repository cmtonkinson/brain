"""Registry loader and query utilities."""

from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .pipeline_validation import PipelineValidationContext, validate_pipeline_skill
from .registry_schema import (
    AutonomyLevel,
    EntrypointRuntime,
    OpDefinition,
    OpRegistry,
    OpRuntime,
    RateLimit,
    SkillDefinition,
    SkillRegistry,
    SkillKind,
    SkillStatus,
)
from .registry_validation import (
    RegistryIndex,
    load_json,
    load_yaml,
    validate_op_registry_data,
    validate_overlay_data,
    validate_registry_data,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChannelPolicy:
    """Allow/deny lists scoped to communication channels."""

    allow: set[str]
    deny: set[str]


@dataclass(frozen=True)
class ActorPolicy:
    """Allow/deny lists scoped to actors."""

    allow: set[str]
    deny: set[str]


@dataclass(frozen=True)
class SkillRuntimeEntry:
    """Resolved skill definition with runtime policy metadata."""

    definition: SkillDefinition
    status: SkillStatus
    autonomy: AutonomyLevel
    rate_limit: RateLimit | None
    channels: ChannelPolicy | None
    actors: ActorPolicy | None


@dataclass(frozen=True)
class SkillRegistryView:
    """Resolved view of the skill registry."""

    registry_version: str
    skills: list[SkillRuntimeEntry]


@dataclass(frozen=True)
class OpRuntimeEntry:
    """Runtime-ready op entry with applied overrides."""

    definition: OpDefinition
    status: SkillStatus
    autonomy: AutonomyLevel
    rate_limit: RateLimit | None
    channels: ChannelPolicy | None
    actors: ActorPolicy | None


@dataclass(frozen=True)
class OpRegistryView:
    """Resolved view of the op registry."""

    registry_version: str
    ops: list[OpRuntimeEntry]


class SkillRegistryLoader:
    """Load the base registry and apply optional overlays."""

    def __init__(
        self,
        base_path: Path | None = None,
        overlay_paths: Iterable[Path] | None = None,
        capability_path: Path | None = None,
        op_registry_path: Path | None = None,
    ) -> None:
        """Initialize the skill registry loader."""
        self._base_path = base_path or Path("/config/skill-registry.json")
        self._capability_path = capability_path or Path("/config/capabilities.json")
        self._op_registry_path = op_registry_path or Path("/config/op-registry.json")
        self._overlay_paths = (
            list(overlay_paths)
            if overlay_paths is not None
            else [
                Path("/config/skill-registry.local.yml"),
                Path("~/.config/brain/skill-registry.local.yml").expanduser(),
            ]
        )
        self._cached_view: SkillRegistryView | None = None
        self._cached_mtimes: dict[Path, float] = {}

    def load(self) -> SkillRegistryView:
        """Load the skill registry and cache the view."""
        view = self._load_registry()
        self._cached_view = view
        self._cached_mtimes = self._current_mtimes()
        return view

    def reload_if_changed(self) -> SkillRegistryView:
        """Reload the skill registry when any registry file changes."""
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
        """List skills filtered by status and capability."""
        view = self.reload_if_changed()
        skills = view.skills
        if status is not None:
            skills = [skill for skill in skills if skill.status == status]
        if capability is not None:
            skills = [skill for skill in skills if capability in skill.definition.capabilities]
        return skills

    def get_skill(self, name: str, version: str | None = None) -> SkillRuntimeEntry:
        """Resolve a skill by name/version."""
        matches = [
            skill for skill in self.reload_if_changed().skills if skill.definition.name == name
        ]
        if version is not None:
            matches = [skill for skill in matches if skill.definition.version == version]
        if not matches:
            raise KeyError(f"skill not found: {name}@{version or '*'}")
        if len(matches) > 1:
            raise ValueError(f"multiple skill versions found for {name}")
        return matches[0]

    def _current_mtimes(self) -> dict[Path, float]:
        """Return modification times for registry-related files."""
        mtimes: dict[Path, float] = {}
        paths = [self._base_path, self._op_registry_path] + list(self._overlay_paths)
        for path in paths:
            if path.exists():
                mtimes[path] = path.stat().st_mtime
        return mtimes

    def _load_registry(self) -> SkillRegistryView:
        """Load the skill registry, validate, and apply overlays."""
        if not self._base_path.exists():
            raise FileNotFoundError(f"registry file not found: {self._base_path}")
        if not self._op_registry_path.exists():
            raise FileNotFoundError(f"op registry file not found: {self._op_registry_path}")

        registry_data = load_json(self._base_path)
        capability_ids = _load_capability_ids(self._capability_path)
        op_registry_data = load_json(self._op_registry_path)
        op_registry = OpRegistry.model_validate(op_registry_data)
        op_registry_errors = validate_op_registry_data(op_registry_data, capability_ids)
        if op_registry_errors:
            raise ValueError("op registry validation failed: " + "; ".join(op_registry_errors))
        op_index = RegistryIndex.from_op_registry(op_registry)
        registry_errors = validate_registry_data(
            registry_data,
            capability_ids,
            op_index=op_index,
            op_registry=op_registry,
        )
        if registry_errors:
            raise ValueError("registry validation failed: " + "; ".join(registry_errors))

        registry = SkillRegistry.model_validate(registry_data)
        registry_index = RegistryIndex.from_registry(registry)
        overrides = _load_overrides(self._overlay_paths, registry_index, entry_label="skill")

        entries: list[SkillRuntimeEntry] = []
        for skill in registry.skills:
            if skill.kind == SkillKind.pipeline:
                context = PipelineValidationContext(
                    skills_by_key={(entry.name, entry.version): entry for entry in registry.skills},
                    ops_by_key={(entry.name, entry.version): entry for entry in op_registry.ops},
                )
                pipeline_errors, computed_caps = validate_pipeline_skill(skill, context)
                if pipeline_errors:
                    raise ValueError("pipeline validation failed: " + "; ".join(pipeline_errors))
                if skill.capabilities and set(skill.capabilities) != computed_caps:
                    raise ValueError(
                        f"pipeline capability mismatch for {skill.name}: "
                        f"{sorted(skill.capabilities)} vs {sorted(computed_caps)}"
                    )
                if not skill.capabilities:
                    skill = skill.model_copy(update={"capabilities": sorted(computed_caps)})
            entry = _apply_overrides(skill, overrides)
            if _should_skip_entry(entry):
                continue
            entries.append(entry)
        return SkillRegistryView(registry_version=registry.registry_version, skills=entries)


class OpRegistryLoader:
    """Load the op registry and apply optional overlays."""

    def __init__(
        self,
        base_path: Path | None = None,
        overlay_paths: Iterable[Path] | None = None,
        capability_path: Path | None = None,
    ) -> None:
        """Initialize the op registry loader."""
        self._base_path = base_path or Path("/config/op-registry.json")
        self._capability_path = capability_path or Path("/config/capabilities.json")
        self._overlay_paths = (
            list(overlay_paths)
            if overlay_paths is not None
            else [
                Path("/config/op-registry.local.yml"),
                Path("~/.config/brain/op-registry.local.yml").expanduser(),
            ]
        )
        self._cached_view: OpRegistryView | None = None
        self._cached_mtimes: dict[Path, float] = {}

    def load(self) -> OpRegistryView:
        """Load the op registry and cache the view."""
        view = self._load_registry()
        self._cached_view = view
        self._cached_mtimes = self._current_mtimes()
        return view

    def reload_if_changed(self) -> OpRegistryView:
        """Reload the op registry when any registry file changes."""
        if self._cached_view is None:
            return self.load()
        if self._cached_mtimes != self._current_mtimes():
            return self.load()
        return self._cached_view

    def list_ops(
        self,
        status: SkillStatus | None = None,
        capability: str | None = None,
    ) -> list[OpRuntimeEntry]:
        """List ops filtered by status and capability."""
        view = self.reload_if_changed()
        ops = view.ops
        if status is not None:
            ops = [op for op in ops if op.status == status]
        if capability is not None:
            ops = [op for op in ops if capability in op.definition.capabilities]
        return ops

    def get_op(self, name: str, version: str | None = None) -> OpRuntimeEntry:
        """Resolve an op by name/version."""
        matches = [op for op in self.reload_if_changed().ops if op.definition.name == name]
        if version is not None:
            matches = [op for op in matches if op.definition.version == version]
        if not matches:
            raise KeyError(f"op not found: {name}@{version or '*'}")
        if len(matches) > 1:
            raise ValueError(f"multiple op versions found for {name}")
        return matches[0]

    def _current_mtimes(self) -> dict[Path, float]:
        """Return modification times for op registry files."""
        mtimes: dict[Path, float] = {}
        paths = [self._base_path] + list(self._overlay_paths)
        for path in paths:
            if path.exists():
                mtimes[path] = path.stat().st_mtime
        return mtimes

    def _load_registry(self) -> OpRegistryView:
        """Load the op registry and apply overlays."""
        if not self._base_path.exists():
            raise FileNotFoundError(f"op registry file not found: {self._base_path}")

        registry_data = load_json(self._base_path)
        capability_ids = _load_capability_ids(self._capability_path)
        registry_errors = validate_op_registry_data(registry_data, capability_ids)
        if registry_errors:
            raise ValueError("op registry validation failed: " + "; ".join(registry_errors))

        registry = OpRegistry.model_validate(registry_data)
        registry_index = RegistryIndex.from_op_registry(registry)
        overrides = _load_overrides(self._overlay_paths, registry_index, entry_label="op")

        entries: list[OpRuntimeEntry] = []
        for op_entry in registry.ops:
            entry = _apply_op_overrides(op_entry, overrides)
            if _should_skip_op_entry(entry):
                continue
            entries.append(entry)
        return OpRegistryView(registry_version=registry.registry_version, ops=entries)


def _load_capability_ids(path: Path) -> set[str]:
    """Load capability identifiers from the capability registry."""
    if not path.exists():
        raise FileNotFoundError(f"capability list not found: {path}")
    data = load_json(path)
    return {entry["id"] for entry in data.get("capabilities", [])}


def _load_overrides(
    overlay_paths: Iterable[Path],
    registry_index: RegistryIndex,
    *,
    entry_label: str = "skill",
) -> list[dict[str, object]]:
    """Load and validate overlay data for a registry."""
    overrides: list[dict[str, object]] = []
    for overlay_path in overlay_paths:
        if not overlay_path.exists():
            continue
        overlay_data = load_yaml(overlay_path)
        overlay_errors = validate_overlay_data(
            overlay_data,
            registry_index,
            entry_label=entry_label,
        )
        if overlay_errors:
            raise ValueError(
                f"overlay validation failed for {overlay_path}: " + "; ".join(overlay_errors)
            )
        overrides.extend(overlay_data.get("overrides", []))
    return overrides


def _apply_overrides(
    skill: SkillDefinition,
    overrides: Iterable[dict[str, object]],
) -> SkillRuntimeEntry:
    """Apply overlay overrides to a skill definition."""
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


def _apply_op_overrides(
    op_entry: OpDefinition,
    overrides: Iterable[dict[str, object]],
) -> OpRuntimeEntry:
    """Apply overlay overrides to an op definition."""
    status = op_entry.status
    autonomy = op_entry.autonomy
    rate_limit = op_entry.rate_limit
    channels: ChannelPolicy | None = None
    actors: ActorPolicy | None = None

    for override in overrides:
        if override.get("name") != op_entry.name:
            continue
        override_version = override.get("version")
        if override_version and override_version != op_entry.version:
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

    return OpRuntimeEntry(
        definition=op_entry,
        status=status,
        autonomy=autonomy,
        rate_limit=rate_limit,
        channels=channels,
        actors=actors,
    )


def _should_skip_entry(entry: SkillRuntimeEntry) -> bool:
    """Return True when a disabled skill should be skipped."""
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


def _should_skip_op_entry(entry: OpRuntimeEntry) -> bool:
    """Return True when a disabled op should be skipped."""
    if entry.status != SkillStatus.disabled:
        return False
    if entry.definition.runtime != OpRuntime.native:
        return False
    if not entry.definition.module:
        return True
    try:
        spec = importlib.util.find_spec(entry.definition.module)
    except ModuleNotFoundError:
        spec = None
    if spec is None and not _module_exists_locally(entry.definition.module):
        logger.warning(
            "Skipping disabled op with missing module: %s",
            entry.definition.name,
        )
        return True
    return False


def _module_exists_locally(module_name: str) -> bool:
    """Return True when a module exists within the repo tree."""
    base_dir = Path(__file__).resolve().parents[1]
    module_path = base_dir / (module_name.replace(".", "/") + ".py")
    package_path = base_dir / module_name.replace(".", "/") / "__init__.py"
    return module_path.exists() or package_path.exists()
