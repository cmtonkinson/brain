"""Tests for HealthAggregator and related config models."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from packages.dashboard.config import DashboardConfig, DataSourcePollConfig
from packages.dashboard.data_sources.health import HealthAggregator, HealthConfig
from packages.dashboard.models.health import ComponentHealth


def _make_agg(**kwargs: object) -> HealthAggregator:
    cfg = HealthConfig(**kwargs)
    return HealthAggregator(config=cfg)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_fetch_core_health_returns_none_on_failure() -> None:
    agg = _make_agg()
    with patch("urllib.request.urlopen", side_effect=Exception("timeout")):
        result, detail = agg._fetch_core_health()
    assert result is None
    assert detail is not None


def test_fetch_core_health_parses_json() -> None:
    agg = _make_agg()
    payload = b'{"ready": true, "resources": {}, "services": {}}'
    mock_resp = MagicMock()
    mock_resp.read.return_value = payload
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result, detail = agg._fetch_core_health()
    assert result == {"ready": True, "resources": {}, "services": {}}
    assert detail is None


def test_state_from_core_ok() -> None:
    agg = _make_agg()
    core = {"resources": {"substrate_postgres": {"ready": True, "detail": "ok"}}, "services": {}}
    result = agg._state_from_core("postgres", core, _now())
    assert result.state == "ok"
    assert result.name == "postgres"


def test_state_from_core_no() -> None:
    agg = _make_agg()
    core = {"resources": {"substrate_redis": {"ready": False, "detail": "refused"}}, "services": {}}
    result = agg._state_from_core("redis", core, _now())
    assert result.state == "no"
    assert result.detail == "refused"


def test_state_from_core_unknown_when_core_none() -> None:
    agg = _make_agg()
    result = agg._state_from_core("postgres", None, _now())
    assert result.state == "unknown"


def test_state_from_core_unknown_when_key_missing() -> None:
    agg = _make_agg()
    core = {"resources": {}, "services": {}}
    result = agg._state_from_core("postgres", core, _now())
    assert result.state == "unknown"


def test_probe_agent_ok_fresh_file(tmp_path: Path) -> None:
    hb = tmp_path / "agent.heartbeat"
    hb.write_text("alive")
    agg = _make_agg(agent_heartbeat_path=str(hb), agent_freshness_seconds=30.0)
    result = agg._probe_agent(_now())
    assert result.state == "ok"


def test_probe_agent_no_stale_file(tmp_path: Path) -> None:
    hb = tmp_path / "agent.heartbeat"
    hb.write_text("alive")
    old_time = time.time() - 60
    os.utime(str(hb), (old_time, old_time))
    agg = _make_agg(agent_heartbeat_path=str(hb), agent_freshness_seconds=30.0)
    with patch.object(agg, "_docker_inspect", return_value=None):
        result = agg._probe_agent(_now())
    assert result.state == "no"


def test_probe_agent_unknown_missing_file(tmp_path: Path) -> None:
    agg = _make_agg(agent_heartbeat_path=str(tmp_path / "missing.heartbeat"))
    with patch.object(agg, "_docker_inspect", return_value=None):
        result = agg._probe_agent(_now())
    assert result.state == "unknown"


def test_fetch_returns_seven_components() -> None:
    agg = _make_agg()
    payload = b'{"ready": true, "resources": {"substrate_postgres": {"ready": true}, "substrate_redis": {"ready": true}, "substrate_qdrant": {"ready": true}, "adapter_signal": {"ready": true}, "adapter_litellm": {"ready": true}}, "services": {}}'
    mock_resp = MagicMock()
    mock_resp.read.return_value = payload
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        with patch.object(agg, "_probe_agent", return_value=ComponentHealth(name="agent", state="unknown", checked_at=_now())):
            results = agg._fetch()
    assert len(results) == 7
    names = {r.name for r in results}
    assert names == {"core", "agent", "postgres", "redis", "signal", "qdrant", "gateway"}


def test_dashboard_config_defaults() -> None:
    cfg = DashboardConfig()
    assert cfg.app_title == "Dashboard"
    assert cfg.data_sources.poll_seconds == 2.0


def test_data_source_poll_config_rejects_zero() -> None:
    with pytest.raises(Exception):
        DataSourcePollConfig(poll_seconds=0)
