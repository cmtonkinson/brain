"""Pydantic settings for the UTCP code-mode adapter resource."""

from __future__ import annotations


from pydantic import BaseModel, ConfigDict, Field

from packages.brain_shared.config import CoreRuntimeSettings, resolve_component_settings
from resources.adapters.utcp_code_mode.adapter import (
    UtcpOperatorCodeModeDefaults,
    UtcpOperatorCodeModeSection,
)
from resources.adapters.utcp_code_mode.component import RESOURCE_COMPONENT_ID


class UtcpCodeModeAdapterSettings(BaseModel):
    """Inline UTCP code-mode configuration under ``adapter.utcp_code_mode``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code_mode: UtcpOperatorCodeModeSection = Field(
        default_factory=lambda: UtcpOperatorCodeModeSection(
            defaults=UtcpOperatorCodeModeDefaults(call_template_type="mcp"),
            servers={},
        )
    )


def resolve_utcp_code_mode_adapter_settings(
    settings: CoreRuntimeSettings,
) -> UtcpCodeModeAdapterSettings:
    """Resolve adapter settings from ``adapter.utcp_code_mode``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(RESOURCE_COMPONENT_ID),
        model=UtcpCodeModeAdapterSettings,
    )
