"""Pydantic settings for the UTCP code-mode adapter resource."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator

from packages.brain_shared.config import BrainSettings, resolve_component_settings
from resources.adapters.utcp_code_mode.component import RESOURCE_COMPONENT_ID


class UtcpCodeModeAdapterSettings(BaseModel):
    """Runtime settings for local UTCP code-mode configuration loading."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    utcp_yaml_config_path: str = "~/.config/brain/utcp.yaml"
    generated_utcp_json_path: str = "~/.cache/brain/utcp.generated.json"

    @field_validator("utcp_yaml_config_path")
    @classmethod
    def _validate_utcp_yaml_config_path(cls, value: str) -> str:
        """Require a non-empty source YAML config path value."""
        normalized = value.strip()
        if normalized == "":
            raise ValueError("utcp_yaml_config_path is required")
        return normalized

    @field_validator("generated_utcp_json_path")
    @classmethod
    def _validate_generated_utcp_json_path(cls, value: str) -> str:
        """Require a non-empty generated UTCP JSON path value."""
        normalized = value.strip()
        if normalized == "":
            raise ValueError("generated_utcp_json_path is required")
        return normalized

    def yaml_config_path(self) -> Path:
        """Return expanded source YAML path for adapter file reads."""
        return Path(self.utcp_yaml_config_path).expanduser()

    def generated_json_path(self) -> Path:
        """Return expanded generated JSON path for adapter writes."""
        return Path(self.generated_utcp_json_path).expanduser()


def resolve_utcp_code_mode_adapter_settings(
    settings: BrainSettings,
) -> UtcpCodeModeAdapterSettings:
    """Resolve adapter settings from ``components.adapter_utcp_code_mode``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(RESOURCE_COMPONENT_ID),
        model=UtcpCodeModeAdapterSettings,
    )
