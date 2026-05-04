"""Pydantic settings for the Coding Adapter resource.

Resolved from the ``adapter.coding`` section of the operator's config. The
catalog is keyed by :class:`~resources.adapters.coding.adapter.ExecutorId`
string values.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from lib.shared.config import CoreRuntimeSettings, resolve_component_settings
from resources.adapters.coding.adapter import ExecutorId
from resources.adapters.coding.component import RESOURCE_COMPONENT_ID


class CodingExecutorSettings(BaseModel):
    """CLI invocation settings for one configured executor.

    The image used to spawn task containers is no longer keyed on the
    executor; every supported agent CLI is baked into a single
    ``brain/coding-runtime:base`` image. Executor entries here only
    describe the in-container CLI binary name and the secret env keys to
    inject from ``secrets.yaml``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cli: str = Field(min_length=1)
    env_keys: tuple[str, ...] = ()


class CodingAdapterSettings(BaseModel):
    """Coding Adapter settings under ``adapter.coding``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    docker_socket: str = Field(default="/var/run/docker.sock", min_length=1)
    owner_label: str = Field(default="brain.coding.owner", min_length=1)
    client_timeout_seconds: int = Field(default=30, gt=0)
    stop_timeout_seconds_max: int = Field(default=30, gt=0)
    base_image: str = Field(default="brain/coding-runtime:base", min_length=1)
    workspace_image_root: str = Field(
        default="~/.config/brain/coding_images",
        min_length=1,
    )
    workspace_image_repo: str = Field(
        default="brain/coding-runtime",
        min_length=1,
    )
    executors: dict[ExecutorId, CodingExecutorSettings] = Field(default_factory=dict)


def resolve_coding_adapter_settings(
    settings: CoreRuntimeSettings,
) -> CodingAdapterSettings:
    """Resolve adapter settings from ``adapter.coding``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(RESOURCE_COMPONENT_ID),
        model=CodingAdapterSettings,
    )
