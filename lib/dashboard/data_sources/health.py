"""Health aggregator data source — probes all 7 system components."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from math import ceil

from pydantic import BaseModel, ConfigDict, Field

from lib.dashboard.data_sources.base import BasePollingDataSource
from lib.dashboard.data_sources.postgres import normalize_postgres_dsn
from lib.dashboard.models.data_source import RetentionPolicy
from lib.dashboard.models.health import ComponentHealth

COMPONENTS = ("core", "assistant", "postgres", "valkey", "signal", "qdrant", "gateway")


class HealthConfig(BaseModel):
    """Resolved runtime settings for direct dashboard health probes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    core_health_url: str = "http://localhost:8898/health"
    core_timeout_seconds: float = Field(default=1.0, gt=0)
    assistant_heartbeat_path: str = "./var/assistant.heartbeat"
    assistant_freshness_seconds: float = Field(default=30.0, gt=0)
    postgres_url: str = "postgresql+psycopg://brain:brain@localhost:8760/brain"
    postgres_timeout_seconds: float = Field(default=1.0, gt=0)
    valkey_url: str = "valkey://localhost:8761/0"
    valkey_connect_timeout_seconds: float = Field(default=1.0, gt=0)
    valkey_socket_timeout_seconds: float = Field(default=1.0, gt=0)
    signal_health_url: str | None = None
    signal_timeout_seconds: float = Field(default=0.5, gt=0)
    qdrant_health_url: str = "http://localhost:8762/healthz"
    qdrant_timeout_seconds: float = Field(default=2.0, gt=0)
    gateway_health_url: str | None = None
    gateway_timeout_seconds: float = Field(default=2.0, gt=0)


class HealthAggregator(BasePollingDataSource[list[ComponentHealth]]):
    """Poll canonical read-only health probes for the dashboard header."""

    def __init__(self, config: HealthConfig, poll_interval: float = 2.0) -> None:
        super().__init__(
            poll_interval, RetentionPolicy(family="snapshot", max_items=50)
        )
        self._config = config

    def _fetch(self) -> list[ComponentHealth]:
        """Run one direct probe per header component in canonical order."""
        now = datetime.now(timezone.utc)
        return [
            self._probe_http_component(
                name="core",
                url=self._config.core_health_url,
                timeout_seconds=self._config.core_timeout_seconds,
                now=now,
            ),
            self._probe_assistant(now),
            self._probe_postgres(now),
            self._probe_valkey(now),
            self._probe_http_component(
                name="signal",
                url=self._config.signal_health_url,
                timeout_seconds=self._config.signal_timeout_seconds,
                now=now,
            ),
            self._probe_http_component(
                name="qdrant",
                url=self._config.qdrant_health_url,
                timeout_seconds=self._config.qdrant_timeout_seconds,
                now=now,
            ),
            self._probe_http_component(
                name="gateway",
                url=self._config.gateway_health_url,
                timeout_seconds=self._config.gateway_timeout_seconds,
                now=now,
            ),
        ]

    def _probe_http_component(
        self,
        *,
        name: str,
        url: str | None,
        timeout_seconds: float,
        now: datetime,
    ) -> ComponentHealth:
        """Probe one HTTP health endpoint with direct, no-fallback semantics."""
        if url is None or url.strip() == "":
            return self._component(
                name=name,
                state="unknown",
                detail="health endpoint not configured",
                now=now,
            )
        try:
            with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
                payload = response.read()
        except urllib.error.HTTPError as exc:
            return self._component(
                name=name,
                state="no",
                detail=f"HTTP {exc.code}",
                now=now,
            )
        except Exception as exc:  # noqa: BLE001
            return self._component(
                name=name,
                state="unknown",
                detail=str(exc) or type(exc).__name__,
                now=now,
            )

        state, detail = self._state_from_http_payload(payload)
        return self._component(name=name, state=state, detail=detail, now=now)

    def _probe_assistant(self, now: datetime) -> ComponentHealth:
        """Probe assistant liveness from heartbeat freshness only."""
        path = self._config.assistant_heartbeat_path
        try:
            mtime = os.path.getmtime(path)
            age = time.time() - mtime
            if age < self._config.assistant_freshness_seconds:
                return self._component(
                    name="assistant", state="ok", detail=None, now=now
                )
            return self._component(
                name="assistant",
                state="no",
                detail=f"heartbeat stale ({age:.0f}s)",
                now=now,
            )
        except OSError as exc:
            return self._component(
                name="assistant",
                state="unknown",
                detail=str(exc) or type(exc).__name__,
                now=now,
            )

    def _probe_postgres(self, now: datetime) -> ComponentHealth:
        """Probe Postgres with one read-only connection-level health query."""
        import psycopg  # noqa: PLC0415

        try:
            with psycopg.connect(
                normalize_postgres_dsn(self._config.postgres_url),
                autocommit=True,
                options="-c default_transaction_read_only=on",
                connect_timeout=max(1, ceil(self._config.postgres_timeout_seconds)),
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
        except Exception as exc:  # noqa: BLE001
            state = "unknown"
            lowered = (str(exc) or type(exc).__name__).lower()
            if (
                "refused" in lowered
                or "authentication" in lowered
                or "password" in lowered
            ):
                state = "no"
            return self._component(
                name="postgres",
                state=state,
                detail=str(exc) or type(exc).__name__,
                now=now,
            )
        return self._component(name="postgres", state="ok", detail=None, now=now)

    def _probe_valkey(self, now: datetime) -> ComponentHealth:
        """Probe Valkey with one direct PING."""
        import valkey  # noqa: PLC0415

        client = None
        try:
            client = valkey.Valkey.from_url(
                self._config.valkey_url,
                socket_connect_timeout=self._config.valkey_connect_timeout_seconds,
                socket_timeout=self._config.valkey_socket_timeout_seconds,
                decode_responses=True,
            )
            ready = bool(client.ping())
        except Exception as exc:  # noqa: BLE001
            state = "unknown"
            lowered = (str(exc) or type(exc).__name__).lower()
            if "refused" in lowered or "auth" in lowered or "wrongpass" in lowered:
                state = "no"
            return self._component(
                name="valkey",
                state=state,
                detail=str(exc) or type(exc).__name__,
                now=now,
            )
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:  # noqa: BLE001
                    pass

        state = "ok" if ready else "no"
        detail = None if ready else "PING returned false"
        return self._component(name="valkey", state=state, detail=detail, now=now)

    def _component(
        self,
        *,
        name: str,
        state: str,
        detail: str | None,
        now: datetime,
    ) -> ComponentHealth:
        """Build one canonical component record."""
        return ComponentHealth(
            name=name,
            state=state,
            detail=detail,
            checked_at=now,
        )

    def _state_from_http_payload(self, payload: bytes) -> tuple[str, str | None]:
        """Normalize one HTTP payload into canonical dashboard state."""
        text = payload.decode("utf-8", errors="ignore").strip()
        if text == "":
            return "ok", None
        try:
            body = json.loads(text)
        except json.JSONDecodeError:
            return "ok", None

        if not isinstance(body, dict):
            return "ok", None

        detail = self._detail_from_payload(body)
        status = body.get("status")
        if (
            body.get("ready") is False
            or body.get("ok") is False
            or body.get("healthy") is False
        ):
            return "no", detail
        if isinstance(status, str) and status.lower() in {
            "error",
            "failed",
            "down",
            "unhealthy",
        }:
            return "no", detail
        return "ok", None

    def _detail_from_payload(self, payload: dict[str, object]) -> str | None:
        """Extract one concise detail string from a JSON health payload."""
        for key in ("detail", "error", "message", "status"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip() != "":
                return value.strip()
        return None
