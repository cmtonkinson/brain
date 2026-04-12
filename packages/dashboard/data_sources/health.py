"""Health aggregator data source — probes all 7 system components."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from packages.dashboard.data_sources.base import BasePollingDataSource
from packages.dashboard.models.data_source import RetentionPolicy
from packages.dashboard.models.health import ComponentHealth


COMPONENTS = ["core", "agent", "postgres", "redis", "signal", "qdrant", "gateway"]

# Keys in core's /health response that map to our component names.
_CORE_SUBSTRATE_MAP = {
    "postgres": "substrate_postgres",
    "redis": "substrate_redis",
    "qdrant": "substrate_qdrant",
    "signal": "adapter_signal",
    "gateway": "adapter_litellm",
}


class HealthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    core_health_url: str = "http://localhost:8898/health"
    agent_heartbeat_path: str = "./var/agent.heartbeat"
    agent_freshness_seconds: float = Field(default=30.0, gt=0)
    probe_timeout_seconds: float = Field(default=2.0, gt=0)


class HealthAggregator(BasePollingDataSource[list[ComponentHealth]]):
    def __init__(self, config: HealthConfig, poll_interval: float = 2.0) -> None:
        super().__init__(
            poll_interval, RetentionPolicy(family="snapshot", max_items=50)
        )
        self._config = config

    def _fetch(self) -> list[ComponentHealth]:
        now = datetime.now(timezone.utc)
        core_health, core_detail = self._fetch_core_health()

        results: list[ComponentHealth] = []

        # core — determined directly from HTTP probe
        results.append(
            ComponentHealth(
                name="core",
                state="ok" if core_health is not None else "no",
                detail=core_detail if core_health is None else None,
                checked_at=now,
            )
        )

        # agent — heartbeat file, then docker inspect
        results.append(self._probe_agent(now))

        # postgres, redis, qdrant, signal, gateway — read from core's health payload
        for component in ("postgres", "redis", "signal", "qdrant", "gateway"):
            results.append(
                self._state_from_core(component, core_health, now)
            )

        return results

    def _fetch_core_health(self) -> tuple[dict | None, str | None]:
        """Fetch and parse core /health JSON. Returns (parsed_dict, None) on success,
        (None, error_detail) on failure."""
        try:
            with urllib.request.urlopen(
                self._config.core_health_url,
                timeout=self._config.probe_timeout_seconds,
            ) as resp:
                return json.loads(resp.read()), None
        except urllib.error.HTTPError as e:
            return None, f"HTTP {e.code}"
        except Exception as e:
            return None, str(e)

    def _state_from_core(
        self, component: str, core_health: dict | None, now: datetime
    ) -> ComponentHealth:
        """Derive a component's state from core's /health payload."""
        if core_health is None:
            return ComponentHealth(name=component, state="unknown", checked_at=now)
        key = _CORE_SUBSTRATE_MAP.get(component)
        if key is None:
            return ComponentHealth(name=component, state="unknown", checked_at=now)
        resources = core_health.get("resources", {})
        services = core_health.get("services", {})
        entry = resources.get(key) or services.get(key)
        if entry is None:
            return ComponentHealth(name=component, state="unknown", checked_at=now)
        ready = entry.get("ready", False)
        detail = entry.get("detail") if not ready else None
        return ComponentHealth(
            name=component,
            state="ok" if ready else "no",
            detail=detail,
            checked_at=now,
        )

    def _probe_agent(self, now: datetime) -> ComponentHealth:
        path = self._config.agent_heartbeat_path
        try:
            mtime = os.path.getmtime(path)
            age = time.time() - mtime
            if age < self._config.agent_freshness_seconds:
                return ComponentHealth(name="agent", state="ok", checked_at=now)
            return ComponentHealth(
                name="agent",
                state="no",
                detail=f"heartbeat stale ({age:.0f}s)",
                checked_at=now,
            )
        except OSError:
            pass
        fallback = self._docker_inspect("brain-brain-agent-1", "agent", now)
        return fallback or ComponentHealth(
            name="agent", state="unknown", checked_at=now
        )

    def _docker_inspect(
        self, container_name: str, component_name: str, now: datetime
    ) -> ComponentHealth | None:
        """Returns ComponentHealth from docker inspect, or None if docker unavailable."""
        try:
            import docker  # type: ignore[import-untyped]

            client = docker.from_env()
            container = client.containers.get(container_name)
            status = container.status
            health = (
                container.attrs.get("State", {}).get("Health", {}).get("Status", "")
            )
            if status == "running" and health in ("healthy", ""):
                return ComponentHealth(name=component_name, state="ok", checked_at=now)
            if status in ("exited", "dead") or health == "unhealthy":
                return ComponentHealth(name=component_name, state="no", checked_at=now)
            return ComponentHealth(
                name=component_name, state="unknown", checked_at=now
            )
        except Exception:
            return None
