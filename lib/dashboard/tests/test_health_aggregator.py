"""Tests for HealthAggregator and related config models."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lib.dashboard.config import (
    DashboardConfig,
    DataSourcePollConfig,
    load_dashboard_config,
)
from lib.dashboard.data_sources.health import HealthAggregator, HealthConfig
from lib.dashboard.models.health import ComponentHealth


def _make_agg(**kwargs: object) -> HealthAggregator:
    cfg = HealthConfig(**kwargs)
    return HealthAggregator(config=cfg)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mock_response(payload: bytes) -> MagicMock:
    response = MagicMock()
    response.read.return_value = payload
    response.__enter__ = lambda s: s
    response.__exit__ = MagicMock(return_value=False)
    return response


def test_probe_core_returns_unknown_on_failure() -> None:
    agg = _make_agg()
    with patch("urllib.request.urlopen", side_effect=Exception("timeout")):
        result = agg._probe_http_component(
            name="core",
            url=agg._config.core_health_url,
            timeout_seconds=agg._config.core_timeout_seconds,
            now=_now(),
        )
    assert result.state == "unknown"
    assert result.detail == "timeout"


def test_probe_core_maps_ready_false_to_no() -> None:
    agg = _make_agg()
    with patch(
        "urllib.request.urlopen",
        return_value=_mock_response(b'{"ready": false, "detail": "booting"}'),
    ):
        result = agg._probe_http_component(
            name="core",
            url=agg._config.core_health_url,
            timeout_seconds=agg._config.core_timeout_seconds,
            now=_now(),
        )
    assert result.state == "no"
    assert result.detail == "booting"


def test_probe_assistant_ok_fresh_file(tmp_path: Path) -> None:
    hb = tmp_path / "assistant.heartbeat"
    hb.write_text("alive")
    agg = _make_agg(assistant_heartbeat_path=str(hb), assistant_freshness_seconds=30.0)
    result = agg._probe_assistant(_now())
    assert result.state == "ok"


def test_probe_assistant_no_stale_file(tmp_path: Path) -> None:
    hb = tmp_path / "assistant.heartbeat"
    hb.write_text("alive")
    old_time = time.time() - 60
    os.utime(str(hb), (old_time, old_time))
    agg = _make_agg(assistant_heartbeat_path=str(hb), assistant_freshness_seconds=30.0)
    result = agg._probe_assistant(_now())
    assert result.state == "no"


def test_probe_assistant_unknown_missing_file(tmp_path: Path) -> None:
    agg = _make_agg(assistant_heartbeat_path=str(tmp_path / "missing.heartbeat"))
    result = agg._probe_assistant(_now())
    assert result.state == "unknown"


def test_probe_postgres_ok() -> None:
    agg = _make_agg()
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.__exit__.return_value = False
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = False
    connection.cursor.return_value = cursor
    with patch("psycopg.connect", return_value=connection):
        result = agg._probe_postgres(_now())
    assert result.state == "ok"


def test_probe_valkey_ok() -> None:
    agg = _make_agg()
    client = MagicMock()
    client.ping.return_value = True
    with patch("valkey.Valkey.from_url", return_value=client):
        result = agg._probe_valkey(_now())
    assert result.state == "ok"
    client.close.assert_called_once()


def test_fetch_returns_seven_components() -> None:
    agg = _make_agg()
    with patch.object(
        agg,
        "_probe_http_component",
        side_effect=[
            ComponentHealth(name="core", state="ok", checked_at=_now()),
            ComponentHealth(name="signal", state="unknown", checked_at=_now()),
            ComponentHealth(name="qdrant", state="ok", checked_at=_now()),
            ComponentHealth(name="gateway", state="unknown", checked_at=_now()),
        ],
    ):
        with patch.object(
            agg,
            "_probe_assistant",
            return_value=ComponentHealth(
                name="assistant", state="unknown", checked_at=_now()
            ),
        ):
            with patch.object(
                agg,
                "_probe_postgres",
                return_value=ComponentHealth(
                    name="postgres", state="ok", checked_at=_now()
                ),
            ):
                with patch.object(
                    agg,
                    "_probe_valkey",
                    return_value=ComponentHealth(
                        name="valkey", state="ok", checked_at=_now()
                    ),
                ):
                    results = agg._fetch()
    assert len(results) == 7
    names = {r.name for r in results}
    assert names == {
        "core",
        "assistant",
        "postgres",
        "valkey",
        "signal",
        "qdrant",
        "gateway",
    }


def test_dashboard_config_defaults() -> None:
    cfg = DashboardConfig()
    assert cfg.app_title == "Dashboard"
    assert cfg.data_sources.poll_seconds == 2.0


def test_data_source_poll_config_rejects_zero() -> None:
    with pytest.raises(Exception):
        DataSourcePollConfig(poll_seconds=0)


def test_load_dashboard_config_sources_runtime_health_defaults(tmp_path: Path) -> None:
    core_file = tmp_path / "core.yaml"
    core_file.write_text(
        "core:\n  http:\n    host: 0.0.0.0\n    port: 9123\n",
        encoding="utf-8",
    )
    resources_file = tmp_path / "resources.yaml"
    resources_file.write_text(
        "\n".join(
            [
                "postgres:",
                "  url: postgresql+psycopg://db-user:db-pass@db-host:5432/brain",
                "  pool_size: 7",
                "  health_timeout_seconds: 3.0",
                "  connect_timeout_seconds: 9.0",
                "valkey:",
                "  url: valkey://cache-host:6380/2",
                "  health_timeout_seconds: 4.0",
                "qdrant:",
                "  url: http://qdrant-host:6333",
                "  request_timeout_seconds: 5.0",
                "signal:",
                "  base_url: http://signal-host:8080",
                "  health_timeout_seconds: 6.0",
            ]
        ),
        encoding="utf-8",
    )
    dashboard_file = tmp_path / "dashboard.yaml"
    dashboard_file.write_text(
        "dashboard:\n  app_title: Ops\n  health:\n    assistant_freshness_seconds: 12.0\n",
        encoding="utf-8",
    )
    gateway_file = tmp_path / "host-mcp-gateway.json"
    gateway_file.write_text(
        json.dumps({"bind_host": "127.0.0.1", "bind_port": 7412}),
        encoding="utf-8",
    )

    config = load_dashboard_config(
        dashboard_config_path=dashboard_file,
        core_config_path=core_file,
        resources_config_path=resources_file,
        gateway_config_path=gateway_file,
        environ={},
    )

    assert config.app_title == "Ops"
    assert config.health.core_health_url == "http://127.0.0.1:9123/health"
    assert config.health.assistant_freshness_seconds == 12.0
    assert (
        config.health.postgres_url
        == "postgresql+psycopg://db-user:db-pass@db-host:5432/brain"
    )
    assert config.health.valkey_url == "valkey://cache-host:6380/2"
    assert config.health.signal_health_url == "http://signal-host:8080/v1/health"
    assert config.health.qdrant_health_url == "http://qdrant-host:6333/healthz"
    assert config.health.gateway_health_url == "http://127.0.0.1:7412/health"
    assert config.postgres.pool_size == 7
    assert config.postgres.connect_timeout_seconds == 9.0
