"""Configuration loading utilities built on ``pydantic-settings``."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping
from unittest.mock import patch

from .models import (
    ActorSettings,
    CoreRuntimeSettings,
    CoreSettings,
    DEFAULT_ACTORS_CONFIG_PATH,
    DEFAULT_CORE_CONFIG_PATH,
    DEFAULT_RESOURCES_CONFIG_PATH,
    ResourcesSettings,
)


def load_core_settings(
    *,
    cli_params: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    config_path: str | Path | None = None,
) -> CoreSettings:
    """Load typed Core settings using the Brain precedence cascade."""
    resolved = (
        Path(config_path) if config_path is not None else DEFAULT_CORE_CONFIG_PATH
    )
    previous = CoreSettings._config_path
    CoreSettings._config_path = resolved
    try:
        init_data = dict(cli_params or {})
        if environ is None:
            return CoreSettings(**init_data)
        env_data = {str(k): str(v) for k, v in environ.items()}
        with patch.dict(os.environ, env_data, clear=True):
            return CoreSettings(**init_data)
    finally:
        CoreSettings._config_path = previous


def load_resources_settings(
    *,
    cli_params: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    config_path: str | Path | None = None,
) -> ResourcesSettings:
    """Load typed Resources settings using the Brain precedence cascade."""
    resolved = (
        Path(config_path) if config_path is not None else DEFAULT_RESOURCES_CONFIG_PATH
    )
    previous = ResourcesSettings._config_path
    ResourcesSettings._config_path = resolved
    try:
        init_data = dict(cli_params or {})
        if environ is None:
            return ResourcesSettings(**init_data)
        env_data = {str(k): str(v) for k, v in environ.items()}
        with patch.dict(os.environ, env_data, clear=True):
            return ResourcesSettings(**init_data)
    finally:
        ResourcesSettings._config_path = previous


def load_actor_settings(
    *,
    cli_params: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    config_path: str | Path | None = None,
) -> ActorSettings:
    """Load typed Actor settings using the Brain precedence cascade."""
    resolved = (
        Path(config_path) if config_path is not None else DEFAULT_ACTORS_CONFIG_PATH
    )
    previous = ActorSettings._config_path
    ActorSettings._config_path = resolved
    try:
        init_data = dict(cli_params or {})
        if environ is None:
            return ActorSettings(**init_data)
        env_data = {str(k): str(v) for k, v in environ.items()}
        with patch.dict(os.environ, env_data, clear=True):
            return ActorSettings(**init_data)
    finally:
        ActorSettings._config_path = previous


def load_core_runtime_settings(
    *,
    core_config_path: str | Path | None = None,
    resources_config_path: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> CoreRuntimeSettings:
    """Load combined Core + Resources settings for the Core service process."""
    core = load_core_settings(config_path=core_config_path, environ=environ)
    resources = load_resources_settings(
        config_path=resources_config_path, environ=environ
    )
    return CoreRuntimeSettings(core=core, resources=resources)
