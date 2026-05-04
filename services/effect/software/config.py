"""Pydantic settings for the Software Service."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from lib.shared.config import CoreRuntimeSettings, resolve_component_settings
from resources.adapters.coding.adapter import ExecutorId
from services.effect.software.component import SERVICE_COMPONENT_ID

DEFAULT_STAGING_ROOT = "~/.local/state/brain/software-tasks"
DEFAULT_BRANCH_PREFIX = "brain/software/"
DEFAULT_MAX_WALLCLOCK_SECONDS = 1800
DEFAULT_WORKSPACE_ROOT = "/mount/software"


class SoftwareServiceSettings(BaseModel):
    """Resolved Software Service settings under ``service.software``.

    Workspaces themselves are not declared here; they are persisted via the
    ``code-workspace-register`` op (which carries ``approval: always``).
    These values supply *defaults* for workspace registration when the
    operator omits a field, plus Service-level orchestration knobs that do
    not vary per workspace.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    staging_root: str = Field(default=DEFAULT_STAGING_ROOT, min_length=1)
    workspace_root: str = Field(default=DEFAULT_WORKSPACE_ROOT, min_length=1)
    default_branch_prefix: str = Field(default=DEFAULT_BRANCH_PREFIX, min_length=1)
    default_executor: ExecutorId = ExecutorId.CLAUDE_CODE
    default_max_wallclock_seconds: int = Field(
        default=DEFAULT_MAX_WALLCLOCK_SECONDS,
        gt=0,
    )
    default_test_command: str = ""
    commit_author_name: str = Field(default="Brain", min_length=1)
    commit_author_email: str = Field(default="brain@local", min_length=1)


def resolve_software_service_settings(
    settings: CoreRuntimeSettings,
) -> SoftwareServiceSettings:
    """Resolve service settings from ``service.software``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(SERVICE_COMPONENT_ID),
        model=SoftwareServiceSettings,
    )
