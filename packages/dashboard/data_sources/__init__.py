"""Read-only substrate readers used by the dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import BasePollingDataSource, DataSource

if TYPE_CHECKING:
    from .docker import DockerDataSource
    from .files import FileDataSource
    from .health import HealthAggregator, HealthConfig
    from .logs import DockerLogSource, FileLogSource, LogBuffer, LogDataSource
    from .postgres import BasePostgresDataSource, PostgresConnectionConfig
    from .redis import BaseRedisDataSource, RedisConnectionConfig

__all__ = [
    "BasePollingDataSource",
    "DataSource",
    "DockerDataSource",
    "DockerLogSource",
    "FileDataSource",
    "FileLogSource",
    "HealthAggregator",
    "HealthConfig",
    "LogBuffer",
    "LogDataSource",
    "BasePostgresDataSource",
    "PostgresConnectionConfig",
    "BaseRedisDataSource",
    "RedisConnectionConfig",
]


def __getattr__(name: str) -> object:
    if name in ("HealthAggregator", "HealthConfig"):
        from . import health as _health  # noqa: PLC0415

        return getattr(_health, name)
    if name == "DockerDataSource":
        from .docker import DockerDataSource  # noqa: PLC0415

        return DockerDataSource
    if name == "FileDataSource":
        from .files import FileDataSource  # noqa: PLC0415

        return FileDataSource
    if name in ("DockerLogSource", "FileLogSource", "LogBuffer", "LogDataSource"):
        from . import logs as _logs  # noqa: PLC0415

        return getattr(_logs, name)
    if name == "BasePostgresDataSource":
        from .postgres import BasePostgresDataSource  # noqa: PLC0415

        return BasePostgresDataSource
    if name == "PostgresConnectionConfig":
        from .postgres import PostgresConnectionConfig  # noqa: PLC0415

        return PostgresConnectionConfig
    if name == "BaseRedisDataSource":
        from .redis import BaseRedisDataSource  # noqa: PLC0415

        return BaseRedisDataSource
    if name == "RedisConnectionConfig":
        from .redis import RedisConnectionConfig  # noqa: PLC0415

        return RedisConnectionConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
