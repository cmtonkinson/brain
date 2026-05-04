"""Configuration loading utilities over the merged Brain config directory."""

from __future__ import annotations

import os
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml

from .models import (
    ActorSettings,
    CoreRuntimeSettings,
    CoreSettings,
    DEFAULT_CONFIG_DIR,
    ResourcesSettings,
    SECRETS_CONFIG_PREFIX,
    _deep_merge_mappings,
)

_IGNORED_RUNTIME_FILENAMES = frozenset({"dashboard.yaml", "mcp-adapter.yaml"})
_CORE_COMPONENT_NAMES = frozenset(
    {
        "cache",
        "commitment",
        "delegation",
        "embedding",
        "execution",
        "ingestion",
        "job",
        "language",
        "object",
        "policy",
        "recall",
        "relay",
        "software",
        "utility",
        "vault",
    }
)
_RESOURCE_COMPONENT_NAMES = frozenset(
    {
        "coding",
        "llm",
        "mcp",
        "obsidian",
        "postgres",
        "qdrant",
        "seaweedfs",
        "signal",
        "utcp_code_mode",
        "valkey",
    }
)
_ACTOR_COMPONENT_NAMES = frozenset(
    {
        "assistant",
        "cli",
        "console",
        "subagent",
        "worker",
    }
)
_SHARED_COMPONENT_NAMES = frozenset({"core", "logging", "observability", "profile"})
_KNOWN_RUNTIME_ROOTS = (
    _CORE_COMPONENT_NAMES
    | _RESOURCE_COMPONENT_NAMES
    | _ACTOR_COMPONENT_NAMES
    | _SHARED_COMPONENT_NAMES
)


@contextmanager
def _override_environ(env_data: dict[str, str]) -> Generator[None, None, None]:
    """Temporarily replace os.environ with env_data for the block's duration."""
    saved = os.environ.copy()
    os.environ.clear()
    os.environ.update(env_data)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


def _resolve_config_dir(config_path: str | Path | None, *, default_dir: Path) -> Path:
    """Resolve one config directory from an explicit path or the default."""
    if config_path is None:
        return default_dir
    resolved = Path(config_path)
    return resolved if resolved.is_dir() else resolved.parent


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Load one YAML mapping, returning an empty mapping when absent or invalid."""
    if not path.exists():
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _scan_runtime_yaml_files(config_dir: Path) -> tuple[Path, ...]:
    """Return non-recursive runtime YAML files in deterministic merge order."""
    if not config_dir.exists():
        return ()
    paths = tuple(
        sorted(
            path
            for path in config_dir.iterdir()
            if path.is_file()
            and path.suffix == ".yaml"
            and path.name not in _IGNORED_RUNTIME_FILENAMES
        )
    )
    return paths


def _env_override_mapping(environ: Mapping[str, str]) -> dict[str, Any]:
    """Project canonical `BRAIN_{COMPONENT}__...` env vars into one mapping."""
    merged: dict[str, Any] = {}
    for key, raw_value in environ.items():
        if not key.startswith("BRAIN_"):
            continue
        if key in {"BRAIN_CONFIG_DIR", "BRAIN_DASHBOARD_CONFIG_FILE"}:
            continue
        remainder = key.removeprefix("BRAIN_")
        if "__" not in remainder:
            continue
        component_name, raw_path = remainder.split("__", 1)
        component_key = component_name.strip().lower()
        if component_key == "" or component_key not in _KNOWN_RUNTIME_ROOTS:
            continue
        path_segments = [
            segment.strip().lower()
            for segment in raw_path.split("__")
            if segment.strip() != ""
        ]
        if len(path_segments) == 0:
            continue
        value = yaml.safe_load(raw_value)
        current: dict[str, Any] = {}
        cursor = current
        cursor[component_key] = {}
        component_cursor = cursor[component_key]
        assert isinstance(component_cursor, dict)
        cursor = component_cursor
        for segment in path_segments[:-1]:
            nested: dict[str, Any] = {}
            cursor[segment] = nested
            cursor = nested
        cursor[path_segments[-1]] = value
        merged = _deep_merge_mappings(merged, current)
    return merged


def _merge_cli_params(cli_params: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalize optional CLI parameter overrides into one deep-mergeable mapping."""
    if cli_params is None:
        return {}
    return {str(key): value for key, value in dict(cli_params).items()}


def _load_runtime_mapping(
    *,
    config_dir: Path,
    environ: Mapping[str, str] | None,
    cli_params: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Load and merge all runtime config sources into one canonical mapping."""
    merged: dict[str, Any] = {}
    for yaml_path in _scan_runtime_yaml_files(config_dir):
        merged = _deep_merge_mappings(merged, _load_yaml_mapping(yaml_path))
    if environ is not None:
        merged = _deep_merge_mappings(
            merged,
            _env_override_mapping({str(k): str(v) for k, v in environ.items()}),
        )
    merged = _deep_merge_mappings(merged, _merge_cli_params(cli_params))
    unknown_roots = sorted(set(merged) - _KNOWN_RUNTIME_ROOTS)
    if unknown_roots:
        raise ValueError(f"unknown Brain config root(s): {', '.join(unknown_roots)}")
    return merged


def _core_mapping(runtime_mapping: dict[str, Any]) -> dict[str, Any]:
    """Project the merged runtime mapping into the Core settings model shape."""
    projected: dict[str, Any] = {}
    for key in ("logging", "observability", "profile", "core"):
        if key in runtime_mapping:
            projected[key] = runtime_mapping[key]
    return projected


def _actor_mapping(runtime_mapping: dict[str, Any]) -> dict[str, Any]:
    """Project the merged runtime mapping into the Actor settings model shape."""
    projected: dict[str, Any] = {}
    for key in (
        "logging",
        "observability",
        "core",
        "cli",
        "assistant",
        "console",
        "worker",
        "subagent",
    ):
        if key in runtime_mapping:
            projected[key] = runtime_mapping[key]
    return projected


def load_core_settings(
    *,
    cli_params: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    config_path: str | Path | None = None,
) -> CoreSettings:
    """Load typed Core settings using the merged Brain config directory."""
    config_dir = _resolve_config_dir(config_path, default_dir=CoreSettings._config_path)
    runtime_mapping = _load_runtime_mapping(
        config_dir=config_dir,
        environ=os.environ if environ is None else environ,
        cli_params=cli_params,
    )
    return CoreSettings.model_validate(_core_mapping(runtime_mapping))


def load_resources_settings(
    *,
    cli_params: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    config_path: str | Path | None = None,
) -> ResourcesSettings:
    """Load typed Resources settings using the merged Brain config directory."""
    config_dir = _resolve_config_dir(
        config_path, default_dir=ResourcesSettings._config_path
    )
    runtime_mapping = _load_runtime_mapping(
        config_dir=config_dir,
        environ=os.environ if environ is None else environ,
        cli_params=cli_params,
    )
    resources_mapping = {
        key: value
        for key, value in runtime_mapping.items()
        if key in _RESOURCE_COMPONENT_NAMES
    }
    return ResourcesSettings.model_validate(resources_mapping)


def load_actor_settings(
    *,
    cli_params: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    config_path: str | Path | None = None,
) -> ActorSettings:
    """Load typed Actor settings using the merged Brain config directory."""
    config_dir = _resolve_config_dir(
        config_path, default_dir=ActorSettings._config_path
    )
    runtime_mapping = _load_runtime_mapping(
        config_dir=config_dir,
        environ=os.environ if environ is None else environ,
        cli_params=cli_params,
    )
    return ActorSettings.model_validate(_actor_mapping(runtime_mapping))


def load_core_runtime_settings(
    *,
    core_config_path: str | Path | None = None,
    resources_config_path: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> CoreRuntimeSettings:
    """Load combined Core + Resources settings for the Core service process."""
    config_dir = _resolve_config_dir(
        core_config_path or resources_config_path,
        default_dir=CoreSettings._config_path,
    )
    runtime_mapping = _load_runtime_mapping(
        config_dir=config_dir,
        environ=os.environ if environ is None else environ,
        cli_params=None,
    )
    return CoreRuntimeSettings(
        core=CoreSettings.model_validate(_core_mapping(runtime_mapping)),
        resources=ResourcesSettings.model_validate(
            {
                key: value
                for key, value in runtime_mapping.items()
                if key in _RESOURCE_COMPONENT_NAMES
            }
        ),
        component_settings={
            key: value
            for key, value in runtime_mapping.items()
            if key in (_CORE_COMPONENT_NAMES | _RESOURCE_COMPONENT_NAMES)
            and isinstance(value, dict)
        },
    )


def runtime_config_directory() -> Path:
    """Return the active runtime config directory path.

    ``BRAIN_CONFIG_DIR`` may legitimately point at either a directory or a
    representative file inside it (matching ``_resolve_config_dir``); when
    a file path is given, its parent directory is returned.
    """
    value = os.getenv("BRAIN_CONFIG_DIR", "").strip()
    if value == "":
        return DEFAULT_CONFIG_DIR
    resolved = Path(value)
    return resolved if resolved.is_dir() else resolved.parent


def is_secrets_file(path: Path) -> bool:
    """Return whether one YAML filename is part of the conventional secrets family."""
    return path.stem.startswith(SECRETS_CONFIG_PREFIX)
