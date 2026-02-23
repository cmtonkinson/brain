"""Configuration loading utilities built on ``pydantic-settings``."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping
from unittest.mock import patch

from .models import BrainSettings, settings_type_for


def load_settings(
    *,
    cli_params: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    config_path: str | Path | None = None,
    env_prefix: str = "BRAIN_",
) -> BrainSettings:
    """Load typed settings using the Brain precedence cascade."""
    settings_type = settings_type_for(
        config_path=config_path,
        env_prefix=env_prefix,
    )
    init_data = _as_plain_dict(cli_params) if cli_params is not None else {}
    if environ is None:
        return settings_type(**init_data)
    env_data = {str(key): str(value) for key, value in environ.items()}
    with patch.dict(os.environ, env_data, clear=True):
        return settings_type(**init_data)


def _as_plain_dict(value: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a mapping into plain ``dict`` values recursively."""
    output: dict[str, Any] = {}
    for key, subvalue in value.items():
        if isinstance(subvalue, Mapping):
            output[str(key)] = _as_plain_dict(subvalue)
        else:
            output[str(key)] = subvalue
    return output
