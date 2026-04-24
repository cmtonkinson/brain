"""Dashboard-local configuration models."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field

from lib.dashboard.data_sources.health import HealthConfig
from lib.dashboard.data_sources.postgres import PostgresConnectionConfig
from lib.shared.config import DEFAULT_CONFIG_DIR

DEFAULT_DASHBOARD_CONFIG_PATH = Path.home() / ".config" / "brain" / "dashboard.yaml"
DEFAULT_GATEWAY_CONFIG_PATH = (
    Path.home() / ".config" / "brain" / "host-mcp-gateway.json"
)
SIGNAL_HEALTH_PATH = "/v1/health"


class DataSourcePollConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    poll_seconds: float = Field(default=2.0, gt=0)
    staleness_threshold_seconds: float = Field(default=10.0, gt=0)


class RetentionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    events_recent_seconds: int = Field(default=300, gt=0)
    events_max_items: int = Field(default=5000, gt=0)
    samples_recent_seconds: int = Field(default=600, gt=0)
    samples_max_items: int = Field(default=1200, gt=0)
    snapshots_recent_count: int = Field(default=50, gt=0)


class LogsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    backfill_lines: int = Field(default=200, gt=0)
    buffer_size: int = Field(default=5000, gt=0)
    refresh_seconds: float = Field(default=0.5, gt=0)
    core_log_path: str = Field(default="logs/core.log")
    assistant_log_path: str = Field(default="logs/assistant.log")


class DashboardConfig(BaseModel):
    """Runtime configuration for the out-of-band dashboard."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    app_title: str = Field(default="Dashboard")
    log_follow_enabled: bool = Field(default=True)
    refresh_interval_seconds: float = Field(default=1.0, gt=0)
    data_sources: DataSourcePollConfig = Field(default_factory=DataSourcePollConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    logs: LogsConfig = Field(default_factory=LogsConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    postgres: PostgresConnectionConfig = Field(
        default_factory=lambda: PostgresConnectionConfig(
            url="postgresql://brain:brain@localhost:8760/brain"
        )
    )


def _merge_mappings(
    base: dict[str, Any], override: Mapping[str, Any]
) -> dict[str, Any]:
    """Recursively merge nested mapping overrides into one base mapping."""
    merged = dict(base)
    for key, value in override.items():
        base_value = merged.get(key)
        if isinstance(base_value, dict) and isinstance(value, Mapping):
            merged[key] = _merge_mappings(base_value, value)
        else:
            merged[key] = value
    return merged


def _normalize_bind_host(host: str) -> str:
    """Collapse wildcard bind addresses into loopback probe hosts."""
    normalized = host.strip()
    if normalized in {"", "0.0.0.0", "::"}:
        return "127.0.0.1"
    return normalized


def _replace_url_path(url: str, path: str) -> str:
    """Replace one URL path while preserving scheme, host, and query parts."""
    parsed = urlsplit(url)
    return urlunsplit(
        (parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment)
    )


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Load one YAML mapping, returning an empty mapping when absent or invalid."""
    import yaml  # type: ignore[import-untyped]

    if not path.exists():
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _load_brain_config_mapping(config_path: Path) -> dict[str, Any]:
    """Load one merged Brain runtime config mapping from a file or config dir."""
    if config_path.is_dir():
        merged: dict[str, Any] = {}
        for path in sorted(config_path.iterdir()):
            if (
                not path.is_file()
                or path.suffix != ".yaml"
                or path.name in {"dashboard.yaml", "mcp-adapter.yaml"}
            ):
                continue
            merged = _merge_mappings(merged, _load_yaml_mapping(path))
        return merged
    return _load_yaml_mapping(config_path)


def _int_from_env(environ: Mapping[str, str], key: str, default: int) -> int:
    """Resolve one integer env override with fallback."""
    value = environ.get(key)
    return int(value) if value is not None else default


def _float_from_env(environ: Mapping[str, str], key: str, default: float) -> float:
    """Resolve one float env override with fallback."""
    value = environ.get(key)
    return float(value) if value is not None else default


def _str_from_env(environ: Mapping[str, str], key: str, default: str) -> str:
    """Resolve one string env override with fallback."""
    value = environ.get(key)
    return value if value is not None else default


def _nested(mapping: Mapping[str, Any], *keys: str) -> Any:
    """Return one nested mapping value or None."""
    current: Any = mapping
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _load_gateway_health_url(*, config_path: Path) -> str | None:
    """Resolve the host MCP gateway health URL from its local config file."""
    if not config_path.exists():
        return None
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(raw, dict):
        return None
    host = raw.get("bind_host")
    port = raw.get("bind_port")
    if not isinstance(host, str) or not isinstance(port, int):
        return None
    return f"http://{_normalize_bind_host(host)}:{port}/health"


def _resolved_dashboard_defaults(
    *,
    core_config_path: str | Path | None,
    resources_config_path: str | Path | None,
    gateway_config_path: str | Path | None,
    environ: Mapping[str, str] | None,
) -> DashboardConfig:
    """Build dashboard defaults from Brain config files plus env overrides."""
    env = dict(environ or {})
    core_mapping = _load_brain_config_mapping(
        Path(core_config_path) if core_config_path is not None else DEFAULT_CONFIG_DIR
    )
    resources_mapping = _load_brain_config_mapping(
        Path(resources_config_path)
        if resources_config_path is not None
        else DEFAULT_CONFIG_DIR
    )

    core_host = _str_from_env(
        env,
        "BRAIN_CORE__HTTP__HOST",
        str(_nested(core_mapping, "core", "http", "host") or "0.0.0.0"),
    )
    core_port = _int_from_env(
        env,
        "BRAIN_CORE__HTTP__PORT",
        int(_nested(core_mapping, "core", "http", "port") or 8898),
    )
    core_timeout = _float_from_env(
        env,
        "BRAIN_CORE__HEALTH__MAX_TIMEOUT_SECONDS",
        float(_nested(core_mapping, "core", "health", "max_timeout_seconds") or 1.0),
    )

    postgres_url = _str_from_env(
        env,
        "BRAIN_POSTGRES__URL",
        str(
            _nested(resources_mapping, "postgres", "url")
            or "postgresql://brain:brain@localhost:8760/brain"
        ),
    )
    postgres_pool_size = _int_from_env(
        env,
        "BRAIN_POSTGRES__POOL_SIZE",
        int(_nested(resources_mapping, "postgres", "pool_size") or 5),
    )
    postgres_health_timeout = _float_from_env(
        env,
        "BRAIN_POSTGRES__HEALTH_TIMEOUT_SECONDS",
        float(_nested(resources_mapping, "postgres", "health_timeout_seconds") or 1.0),
    )
    postgres_connect_timeout = _float_from_env(
        env,
        "BRAIN_POSTGRES__CONNECT_TIMEOUT_SECONDS",
        float(
            _nested(resources_mapping, "postgres", "connect_timeout_seconds") or 10.0
        ),
    )

    valkey_url = _str_from_env(
        env,
        "BRAIN_VALKEY__URL",
        str(_nested(resources_mapping, "valkey", "url") or "valkey://localhost:8761/0"),
    )
    valkey_health_timeout = _float_from_env(
        env,
        "BRAIN_VALKEY__HEALTH_TIMEOUT_SECONDS",
        float(_nested(resources_mapping, "valkey", "health_timeout_seconds") or 1.0),
    )

    signal_base_url = _str_from_env(
        env,
        "BRAIN_SIGNAL__BASE_URL",
        str(
            _nested(resources_mapping, "signal", "base_url") or "http://signal-api:8080"
        ),
    )
    signal_health_timeout = _float_from_env(
        env,
        "BRAIN_SIGNAL__HEALTH_TIMEOUT_SECONDS",
        float(_nested(resources_mapping, "signal", "health_timeout_seconds") or 0.5),
    )

    qdrant_url = _str_from_env(
        env,
        "BRAIN_QDRANT__URL",
        str(_nested(resources_mapping, "qdrant", "url") or "http://localhost:8762"),
    )
    qdrant_timeout = _float_from_env(
        env,
        "BRAIN_QDRANT__REQUEST_TIMEOUT_SECONDS",
        float(_nested(resources_mapping, "qdrant", "request_timeout_seconds") or 10.0),
    )

    gateway_health_url = _load_gateway_health_url(
        config_path=(
            Path(gateway_config_path)
            if gateway_config_path is not None
            else DEFAULT_GATEWAY_CONFIG_PATH
        )
    )

    return DashboardConfig(
        health=HealthConfig(
            core_health_url=(
                f"http://{_normalize_bind_host(core_host)}:{core_port}/health"
            ),
            core_timeout_seconds=core_timeout,
            postgres_url=postgres_url,
            postgres_timeout_seconds=postgres_health_timeout,
            valkey_url=valkey_url,
            valkey_connect_timeout_seconds=valkey_health_timeout,
            valkey_socket_timeout_seconds=valkey_health_timeout,
            signal_health_url=_replace_url_path(signal_base_url, SIGNAL_HEALTH_PATH),
            signal_timeout_seconds=signal_health_timeout,
            qdrant_health_url=_replace_url_path(qdrant_url, "/healthz"),
            qdrant_timeout_seconds=qdrant_timeout,
            gateway_health_url=gateway_health_url,
        ),
        postgres=PostgresConnectionConfig(
            url=postgres_url,
            pool_size=postgres_pool_size,
            connect_timeout_seconds=postgres_connect_timeout,
        ),
    )


def load_dashboard_config(
    *,
    dashboard_config_path: str | Path | None = None,
    core_config_path: str | Path | None = None,
    resources_config_path: str | Path | None = None,
    gateway_config_path: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> DashboardConfig:
    """Load dashboard config using Brain config files as the default source."""
    defaults = _resolved_dashboard_defaults(
        core_config_path=core_config_path,
        resources_config_path=resources_config_path,
        gateway_config_path=gateway_config_path,
        environ=environ,
    )
    config_path = (
        Path(dashboard_config_path)
        if dashboard_config_path is not None
        else DEFAULT_DASHBOARD_CONFIG_PATH
    )
    if not config_path.exists():
        return defaults

    raw = _load_yaml_mapping(config_path)
    if not raw:
        return defaults

    merged = _merge_mappings(
        defaults.model_dump(mode="python"),
        raw.get("dashboard", raw),
    )
    return DashboardConfig.model_validate(merged)
