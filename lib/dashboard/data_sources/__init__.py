"""Read-only substrate readers used by the dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import BasePollingDataSource, DataSource

if TYPE_CHECKING:
    from .health import HealthAggregator, HealthConfig
    from .logs import DockerLogSource, FileLogSource, LogBuffer, LogDataSource
    from .postgres import BasePostgresDataSource, PostgresConnectionConfig
    from .valkey import BaseValkeyDataSource, ValkeyConnectionConfig

__all__ = [
    "BasePollingDataSource",
    "DataSource",
    "DockerLogSource",
    "FileLogSource",
    "HealthAggregator",
    "HealthConfig",
    "LogBuffer",
    "LogDataSource",
    "BasePostgresDataSource",
    "PostgresConnectionConfig",
    "BaseValkeyDataSource",
    "ValkeyConnectionConfig",
]


def __getattr__(name: str) -> object:
    if name in ("HealthAggregator", "HealthConfig"):
        from . import health as _health  # noqa: PLC0415

        return getattr(_health, name)
    if name in ("DockerLogSource", "FileLogSource", "LogBuffer", "LogDataSource"):
        from . import logs as _logs  # noqa: PLC0415

        return getattr(_logs, name)
    if name == "BasePostgresDataSource":
        from .postgres import BasePostgresDataSource  # noqa: PLC0415

        return BasePostgresDataSource
    if name == "PostgresConnectionConfig":
        from .postgres import PostgresConnectionConfig  # noqa: PLC0415

        return PostgresConnectionConfig
    if name == "BaseValkeyDataSource":
        from .valkey import BaseValkeyDataSource  # noqa: PLC0415

        return BaseValkeyDataSource
    if name == "ValkeyConnectionConfig":
        from .valkey import ValkeyConnectionConfig  # noqa: PLC0415

        return ValkeyConnectionConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
