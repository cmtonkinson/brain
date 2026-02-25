"""Shared fixtures for integration-oriented test modules."""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Iterator

import pytest

from packages.brain_shared.config import load_settings
from resources.substrates.postgres.config import resolve_postgres_settings
from resources.substrates.qdrant.component import RESOURCE_COMPONENT_ID as QDRANT_ID
from resources.substrates.qdrant.config import QdrantSettings
from resources.substrates.redis.config import resolve_redis_settings
from packages.brain_shared.config import resolve_component_settings
from tests.integration.helpers import real_provider_tests_enabled


@pytest.fixture(scope="session")
def env_settings() -> object:
    """Return loaded settings snapshot for fixture consumers."""
    return load_settings()


@pytest.fixture(scope="function")
def tmp_blob_root(tmp_path: Path) -> Path:
    """Return function-scoped temporary blob root directory."""
    root = tmp_path / "blobs"
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture(scope="function")
def clock_freezer(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Freeze random backoff jitter paths by making randomness deterministic."""
    monkeypatch.setattr("resources.adapters.signal.signal_adapter.random", lambda: 0.5)
    yield


@pytest.fixture(scope="session")
def postgres_dsn(env_settings: object) -> str | None:
    """Return Postgres DSN when real-provider integrations are enabled."""
    if not real_provider_tests_enabled():
        return None
    return resolve_postgres_settings(env_settings).url


@pytest.fixture(scope="session")
def redis_url(env_settings: object) -> str | None:
    """Return Redis URL when real-provider integrations are enabled."""
    if not real_provider_tests_enabled():
        return None
    return resolve_redis_settings(env_settings).url


@pytest.fixture(scope="session")
def qdrant_url(env_settings: object) -> str | None:
    """Return Qdrant URL when real-provider integrations are enabled."""
    if not real_provider_tests_enabled():
        return None
    return resolve_component_settings(
        settings=env_settings,
        component_id=str(QDRANT_ID),
        model=QdrantSettings,
    ).url


def _can_connect(host: str, port: int, timeout: float = 0.5) -> bool:
    """Return True when a TCP connection to host/port succeeds."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def postgres_engine(postgres_dsn: str | None):
    """Return SQLAlchemy engine for real-provider tests or skip if unavailable."""
    if postgres_dsn is None:
        pytest.skip("real-provider integration tests disabled")
    from sqlalchemy import create_engine

    engine = create_engine(postgres_dsn)
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"postgres unavailable for integration tests: {exc}")
    return engine


@pytest.fixture(scope="session")
def redis_client(redis_url: str | None):
    """Return Redis client for real-provider tests or skip if unavailable."""
    if redis_url is None:
        pytest.skip("real-provider integration tests disabled")

    from redis import Redis

    client = Redis.from_url(redis_url)
    try:
        client.ping()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"redis unavailable for integration tests: {exc}")
    return client


@pytest.fixture(scope="session")
def qdrant_client(qdrant_url: str | None):
    """Return Qdrant client for real-provider tests or skip if unavailable."""
    if qdrant_url is None:
        pytest.skip("real-provider integration tests disabled")

    from qdrant_client import QdrantClient

    client = QdrantClient(url=qdrant_url)
    try:
        client.get_collections()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"qdrant unavailable for integration tests: {exc}")
    return client


@pytest.fixture(scope="session")
def http_stub_server() -> None:
    """Placeholder fixture for local HTTP stub-server contract tests.

    The current adapter suites monkeypatch transport calls directly for determinism.
    This fixture exists as the stable integration harness boundary for future
    migration to a socket-backed in-process server.
    """

    return None
