# packages/brain_shared/manifest.py
from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Literal, NewType, Optional

ComponentId = NewType("ComponentId", str)
ResourceId = NewType("ResourceId", str)
ModuleRoot = NewType("ModuleRoot", str)

Layer = Literal[0, 1, 2]
System = Literal["state", "action", "control"]


@dataclass(frozen=True, slots=True)
class ComponentManifest:
    id: ComponentId
    layer: Layer
    module_roots: FrozenSet[ModuleRoot]


# ----------------------------
# L1 Services
# ----------------------------


@dataclass(frozen=True, slots=True)
class ServiceManifest(ComponentManifest):
    layer: Literal[1]
    system: System

    # The only modules outsiders may import from within this Service's namespace.
    public_api_roots: FrozenSet[ModuleRoot]

    # Declarative ownership (used to build resource -> owner map).
    owns_resources: FrozenSet[ResourceId]


# ----------------------------
# L0 Resources
# ----------------------------

ResourceKind = Literal["substrate", "adapter"]


@dataclass(frozen=True, slots=True)
class ResourceManifest(ComponentManifest):
    layer: Literal[0]
    kind: ResourceKind

    # Optional owner, because some things may be intentionally "shared infra".
    owner_service_id: Optional[ComponentId] = None
