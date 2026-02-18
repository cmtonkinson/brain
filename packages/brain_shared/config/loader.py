"""Configuration loading utilities with deterministic precedence.

The cascade is always:
1) CLI params
2) Environment variables
3) ~/.config/brain/brain.yml
4) Built-in defaults

Environment variable format:
- Prefix: ``BRAIN_``
- Nested keys: ``__`` separator
- Example: ``BRAIN_LOGGING__LEVEL=DEBUG`` -> ``logging.level = "DEBUG"``
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .defaults import BUILTIN_DEFAULTS

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "brain" / "brain.yml"


def load_config(
    *,
    cli_params: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    config_path: str | Path | None = None,
    defaults: Mapping[str, Any] | None = None,
    env_prefix: str = "BRAIN_",
) -> dict[str, Any]:
    """Load configuration by applying the standard Brain precedence cascade."""
    merged_defaults = (
        _as_plain_dict(defaults)
        if defaults is not None
        else _as_plain_dict(BUILTIN_DEFAULTS)
    )

    file_data = _load_file_config(path=config_path)
    env_data = _load_env_config(environ=environ, prefix=env_prefix)
    cli_data = _as_plain_dict(cli_params) if cli_params is not None else {}

    merged = _merge_dicts(merged_defaults, file_data)
    merged = _merge_dicts(merged, env_data)
    merged = _merge_dicts(merged, cli_data)
    return merged


def _load_file_config(*, path: str | Path | None) -> dict[str, Any]:
    """Load YAML config from disk; return empty dict when file is absent."""
    resolved = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not resolved.exists():
        return {}

    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "YAML config file detected but PyYAML is not installed. "
            "Install with: pip install pyyaml"
        ) from exc

    with resolved.open("r", encoding="utf-8") as handle:
        parsed = yaml.safe_load(handle)

    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ValueError(f"Config file must contain a top-level mapping: {resolved}")
    return _as_plain_dict(parsed)


def _load_env_config(
    *, environ: Mapping[str, str] | None, prefix: str
) -> dict[str, Any]:
    """Extract and map prefixed environment variables into nested config."""
    env = environ if environ is not None else os.environ
    output: dict[str, Any] = {}

    for key, raw_value in env.items():
        if not key.startswith(prefix):
            continue

        remainder = key[len(prefix) :]
        if not remainder:
            continue

        path = [
            segment.strip().lower()
            for segment in remainder.split("__")
            if segment.strip()
        ]
        if not path:
            continue

        _set_nested(output, path, _coerce_scalar(raw_value))

    return output


def _set_nested(target: dict[str, Any], path: list[str], value: Any) -> None:
    """Set a nested mapping value by path, creating intermediate dicts."""
    cursor: dict[str, Any] = target
    for segment in path[:-1]:
        child = cursor.get(segment)
        if not isinstance(child, dict):
            child = {}
            cursor[segment] = child
        cursor = child
    cursor[path[-1]] = value


def _merge_dicts(
    base: Mapping[str, Any], override: Mapping[str, Any]
) -> dict[str, Any]:
    """Recursively merge mappings, with ``override`` taking precedence."""
    result = _as_plain_dict(base)
    for key, override_value in override.items():
        base_value = result.get(key)
        if isinstance(base_value, dict) and isinstance(override_value, Mapping):
            result[key] = _merge_dicts(base_value, override_value)
            continue
        result[key] = copy.deepcopy(override_value)
    return result


def _coerce_scalar(raw: str) -> Any:
    """Coerce scalar env strings into bool/int/float/JSON when obvious."""
    value = raw.strip()
    lowered = value.lower()

    if lowered in {"true", "false"}:
        return lowered == "true"

    if lowered in {"null", "none"}:
        return None

    if value.startswith("{") or value.startswith("["):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return raw

    try:
        return int(value)
    except ValueError:
        pass

    try:
        return float(value)
    except ValueError:
        return raw


def _as_plain_dict(value: Mapping[str, Any]) -> dict[str, Any]:
    """Deep-copy a mapping into plain ``dict`` values recursively."""
    output: dict[str, Any] = {}
    for key, subvalue in value.items():
        if isinstance(subvalue, Mapping):
            output[str(key)] = _as_plain_dict(subvalue)
        else:
            output[str(key)] = copy.deepcopy(subvalue)
    return output
