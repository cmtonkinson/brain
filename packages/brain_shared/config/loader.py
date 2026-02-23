"""Configuration loading utilities built on ``pydantic-settings``."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping
from unittest.mock import patch

from .models import DEFAULT_CONFIG_PATH, BrainSettings


def load_settings(
    *,
    cli_params: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    config_path: str | Path | None = None,
) -> BrainSettings:
    """Load typed settings using the Brain precedence cascade."""
    resolved_config_path = (
        Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    )
    init_data = dict(cli_params or {})
    previous_config_path = BrainSettings._config_path
    BrainSettings._config_path = resolved_config_path
    try:
        if environ is None:
            return BrainSettings(**init_data)
        env_data = {str(key): str(value) for key, value in environ.items()}
        with patch.dict(os.environ, env_data, clear=True):
            return BrainSettings(**init_data)
    finally:
        BrainSettings._config_path = previous_config_path
