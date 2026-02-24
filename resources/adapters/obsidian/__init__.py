"""Obsidian adapter resource exports."""

from resources.adapters.obsidian.adapter import (
    FileEditOperation,
    ObsidianAdapter,
    ObsidianAdapterAlreadyExistsError,
    ObsidianAdapterConflictError,
    ObsidianAdapterDependencyError,
    ObsidianAdapterError,
    ObsidianAdapterInternalError,
    ObsidianAdapterNotFoundError,
    ObsidianEntry,
    ObsidianEntryType,
    ObsidianFileRecord,
    ObsidianSearchMatch,
)
from resources.adapters.obsidian.component import MANIFEST, RESOURCE_COMPONENT_ID
from resources.adapters.obsidian.config import (
    ObsidianAdapterSettings,
    resolve_obsidian_adapter_settings,
)
from resources.adapters.obsidian.obsidian_adapter import ObsidianLocalRestAdapter

__all__ = [
    "FileEditOperation",
    "MANIFEST",
    "ObsidianAdapter",
    "ObsidianAdapterAlreadyExistsError",
    "ObsidianAdapterConflictError",
    "ObsidianAdapterDependencyError",
    "ObsidianAdapterError",
    "ObsidianAdapterInternalError",
    "ObsidianAdapterNotFoundError",
    "ObsidianAdapterSettings",
    "ObsidianEntry",
    "ObsidianEntryType",
    "ObsidianFileRecord",
    "ObsidianLocalRestAdapter",
    "ObsidianSearchMatch",
    "RESOURCE_COMPONENT_ID",
    "resolve_obsidian_adapter_settings",
]
