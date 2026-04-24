"""Pydantic settings for Delegation Service behavior."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from lib.shared.config import CoreRuntimeSettings, resolve_component_settings
from services.reason.delegation.component import SERVICE_COMPONENT_ID


class DelegationServiceSettings(BaseModel):
    """Delegation Service runtime behavior settings.

    Includes the mechanical recursion guard for nested subagent invocations.
    The depth ceiling is enforced server-side at insert time so a runaway
    parent cannot indirectly spawn an unbounded chain by smuggling
    ``parent_invocation_id`` references.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_recursion_depth: int = Field(default=4, ge=0)
    sweeper_interval_seconds: float = Field(default=30.0, gt=0)


def resolve_delegation_settings(
    settings: CoreRuntimeSettings,
) -> DelegationServiceSettings:
    """Resolve Delegation settings from ``service.delegation``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(SERVICE_COMPONENT_ID),
        model=DelegationServiceSettings,
    )
