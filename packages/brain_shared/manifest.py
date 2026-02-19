"""Authoritative component-manifest model and registry.

This module defines shared manifest primitives for Brain components and provides
registration/validation helpers that can be consumed during bootstrap tasks such
as database schema/domain provisioning before service migrations run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from threading import RLock
from typing import Final, FrozenSet, Literal, NewType, Optional

ComponentId = NewType("ComponentId", str)
ModuleRoot = NewType("ModuleRoot", str)

Layer = Literal[0, 1, 2]
System = Literal["state", "action", "control"]
ResourceKind = Literal["substrate", "adapter"]

_SYSTEM_ORDER: Final[dict[System, int]] = {"state": 0, "action": 1, "control": 2}
_COMPONENT_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]{1,62}$")
_MODULE_ROOT_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*$"
)


class ManifestError(ValueError):
    """Raised when manifest definitions or registration are invalid."""


@dataclass(frozen=True, slots=True)
class ComponentManifest:
    """Base manifest model for any Brain component."""

    id: ComponentId
    layer: Layer
    system: System
    module_roots: FrozenSet[ModuleRoot]

    def __post_init__(self) -> None:
        """Validate base component invariants."""
        validate_component_id(self.id)
        if len(self.module_roots) == 0:
            raise ManifestError("module_roots must not be empty")
        for root in self.module_roots:
            validate_module_root(root)


@dataclass(frozen=True, slots=True)
class ResourceManifest(ComponentManifest):
    """Manifest declaration for an L0 substrate/adapter component."""

    layer: Literal[0]
    kind: ResourceKind

    # Optional owner because some resources are intentionally shared infra.
    owner_service_id: Optional[ComponentId] = None

    def __post_init__(self) -> None:
        """Validate resource-specific invariants."""
        super(ResourceManifest, self).__post_init__()
        if self.owner_service_id is not None:
            validate_component_id(self.owner_service_id)


@dataclass(frozen=True, slots=True)
class ServiceManifest(ComponentManifest):
    """Manifest declaration for an L1 service component."""

    layer: Literal[1]
    public_api_roots: FrozenSet[ModuleRoot]
    owns_resources: Optional[FrozenSet[ComponentId]] = None

    def __post_init__(self) -> None:
        """Validate service-specific invariants."""
        super(ServiceManifest, self).__post_init__()
        if len(self.public_api_roots) == 0:
            raise ManifestError("public_api_roots must not be empty")
        for root in self.public_api_roots:
            validate_module_root(root)

    @property
    def schema_name(self) -> str:
        """Return canonical Postgres schema name derived from service id."""
        return component_id_to_schema_name(self.id)


@dataclass(frozen=True, slots=True)
class ActorManifest(ComponentManifest):
    """Manifest declaration for an L2 actor component."""

    layer: Literal[2]

    # Optional ownership metadata for operations initiated by autonomous actors.
    principal: str = "operator"

    def __post_init__(self) -> None:
        """Validate actor-specific invariants."""
        super(ActorManifest, self).__post_init__()
        if not self.principal:
            raise ManifestError("principal must not be empty")


@dataclass(slots=True)
class ManifestRegistry:
    """In-memory global registry for all component manifests."""

    _components: dict[ComponentId, ComponentManifest] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock)

    def register_component(self, manifest: ComponentManifest) -> None:
        """Register one component manifest with uniqueness validation."""
        with self._lock:
            self._register_component(manifest)
            if self._iter_components_of_type(
                ServiceManifest
            ) or self._iter_components_of_type(ResourceManifest):
                self._validate_service_resource_ownership(strict_owner_existence=False)

    def get_component(self, component_id: ComponentId) -> ComponentManifest:
        """Return any registered component manifest by id."""
        try:
            return self._components[component_id]
        except KeyError as exc:
            raise ManifestError(f"component not registered: {component_id}") from exc

    def list_resources(self) -> tuple[ResourceManifest, ...]:
        """Return all registered resources sorted by id."""
        return tuple(
            sorted(
                self._iter_components_of_type(ResourceManifest),
                key=lambda item: str(item.id),
            )
        )

    def list_services(self) -> tuple[ServiceManifest, ...]:
        """Return all registered services sorted by system and id."""
        return tuple(
            sorted(
                self._iter_components_of_type(ServiceManifest),
                key=lambda item: (_SYSTEM_ORDER[item.system], str(item.id)),
            )
        )

    def list_actors(self) -> tuple[ActorManifest, ...]:
        """Return all registered actors sorted by id."""
        return tuple(
            sorted(
                self._iter_components_of_type(ActorManifest),
                key=lambda item: str(item.id),
            )
        )

    def list_components(self) -> tuple[ComponentManifest, ...]:
        """Return all registered components sorted by id."""
        return tuple(sorted(self._components.values(), key=lambda item: str(item.id)))

    def assert_valid(self) -> None:
        """Re-run full registry invariants and raise on violation."""
        with self._lock:
            self._validate_service_resource_ownership(strict_owner_existence=True)

    def _register_component(self, manifest: ComponentManifest) -> None:
        """Register a component while enforcing global uniqueness."""
        existing = self._components.get(manifest.id)
        if existing is not None and existing != manifest:
            raise ManifestError(
                f"duplicate component id with mismatched definition: {manifest.id}"
            )
        self._components[manifest.id] = manifest

    def _iter_components_of_type(
        self, manifest_type: type[ComponentManifest]
    ) -> tuple[ComponentManifest, ...]:
        """Return components matching one specific manifest subclass type."""
        return tuple(
            component
            for component in self._components.values()
            if isinstance(component, manifest_type)
        )

    def _validate_service_resource_ownership(
        self, *, strict_owner_existence: bool
    ) -> None:
        """Validate declared resource ownership between services/resources."""
        declared_owners: dict[ComponentId, ComponentId] = {}

        for service in self.list_services():
            for resource_id in service.owns_resources or frozenset():
                owner = declared_owners.get(resource_id)
                if owner is not None and owner != service.id:
                    raise ManifestError(
                        f"resource '{resource_id}' has multiple owners: {owner} and {service.id}"
                    )
                declared_owners[resource_id] = service.id

        service_ids = {service.id for service in self.list_services()}
        for resource in self.list_resources():
            if resource.owner_service_id is None:
                continue
            if resource.owner_service_id not in service_ids:
                if strict_owner_existence:
                    raise ManifestError(
                        f"resource '{resource.id}' references unknown owner service '{resource.owner_service_id}'"
                    )
                continue
            expected = declared_owners.get(ComponentId(resource.id))
            if expected is not None and expected != resource.owner_service_id:
                raise ManifestError(
                    f"resource '{resource.id}' owner mismatch: declared owner is '{expected}', "
                    f"resource manifest owner is '{resource.owner_service_id}'"
                )


def validate_component_id(value: ComponentId) -> None:
    """Validate component-id format suitable for schema derivation."""
    raw = str(value)
    if not _COMPONENT_ID_RE.fullmatch(raw):
        raise ManifestError(
            f"invalid component id '{raw}'; expected ^[a-z][a-z0-9_]{{1,62}}$"
        )


def validate_module_root(value: ModuleRoot) -> None:
    """Validate Python module-root path format."""
    raw = str(value)
    if not _MODULE_ROOT_RE.fullmatch(raw):
        raise ManifestError(f"invalid module root '{raw}'")


def component_id_to_schema_name(component_id: ComponentId) -> str:
    """Derive canonical Postgres schema name from component id."""
    validate_component_id(component_id)
    return str(component_id)


_DEFAULT_REGISTRY = ManifestRegistry()


def register_component(manifest: ComponentManifest) -> ComponentManifest:
    """Register a component manifest in the default process-local registry."""
    _DEFAULT_REGISTRY.register_component(manifest)
    return manifest


def get_registry() -> ManifestRegistry:
    """Return the process-local default manifest registry."""
    return _DEFAULT_REGISTRY


def get_component(component_id: ComponentId) -> ComponentManifest:
    """Return one registered component (actor/service/resource) by id."""
    return _DEFAULT_REGISTRY.get_component(component_id)


def list_components() -> tuple[ComponentManifest, ...]:
    """Return all registered components from the global registry."""
    return _DEFAULT_REGISTRY.list_components()
