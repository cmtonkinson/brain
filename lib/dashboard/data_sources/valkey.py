"""Read-only Valkey access for dashboard data sources."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from lib.dashboard.data_sources.base import BasePollingDataSource
from lib.dashboard.models.data_source import RetentionPolicy

T = TypeVar("T")


class ValkeyConnectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    url: str = "valkey://localhost:8761/0"
    connect_timeout_seconds: float = Field(default=5.0, gt=0)
    socket_timeout_seconds: float = Field(default=5.0, gt=0)
    read_only: bool = True


class BaseValkeyDataSource(BasePollingDataSource[T], Generic[T]):
    def __init__(
        self,
        config: ValkeyConnectionConfig,
        poll_interval: float,
        retention: RetentionPolicy,
    ) -> None:
        super().__init__(poll_interval, retention)
        self._config = config
        self._client = None

    def _get_client(self):
        import valkey  # noqa: PLC0415

        if self._client is None:
            self._client = valkey.Valkey.from_url(
                self._config.url,
                socket_connect_timeout=self._config.connect_timeout_seconds,
                socket_timeout=self._config.socket_timeout_seconds,
                decode_responses=True,
            )
        return self._client

    def _fetch(self) -> T | None:
        client = self._get_client()
        client.ping()
        return None  # subclasses override with real queries

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
