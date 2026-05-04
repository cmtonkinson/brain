"""Pydantic settings for the Console adapter resource."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from lib.shared.config import CoreRuntimeSettings, resolve_component_settings
from resources.adapters.console.component import RESOURCE_COMPONENT_ID


class ConsoleAdapterSettings(BaseModel):
    """Runtime settings for the Console inbound adapter.

    The Console adapter is a thin in-process forwarder; no transport tunables
    are required today. The settings model exists for symmetry with the
    Signal adapter and as a place to add future knobs.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


def resolve_console_adapter_settings(
    settings: CoreRuntimeSettings,
) -> ConsoleAdapterSettings:
    """Resolve Console adapter settings from the runtime config tree."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(RESOURCE_COMPONENT_ID),
        model=ConsoleAdapterSettings,
    )
