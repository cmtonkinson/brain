"""Pydantic settings for Execution Service behavior."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from lib.shared.config import CoreRuntimeSettings, resolve_component_settings
from services.effect.execution.component import SERVICE_COMPONENT_ID


class ExecutionSettings(BaseModel):
    """Execution runtime behavior settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    discovery_roots: tuple[str, ...] = ("ops",)
    always_on_op_ids: tuple[str, ...] = ()
    op_search_top_k: int = Field(default=10, ge=1, le=50)


def resolve_execution_settings(
    settings: CoreRuntimeSettings,
) -> ExecutionSettings:
    """Resolve Execution settings from ``service.execution``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(SERVICE_COMPONENT_ID),
        model=ExecutionSettings,
    )
