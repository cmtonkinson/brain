"""Ephemeral container fixtures for integration tests."""

from __future__ import annotations

import socket
import os
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

import pytest
import yaml
from sqlalchemy import create_engine

from packages.brain_core.migrations import run_startup_migrations
from packages.brain_shared.config import (
    CoreRuntimeSettings,
    CoreSettings,
    ResourcesSettings,
)
from resources.substrates.postgres.config import resolve_postgres_settings
from tests.integration.helpers import real_provider_tests_enabled

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE_PATH = _REPO_ROOT / "docker-compose.yaml"
_IMAGE_DEFAULTS: dict[str, str] = {
    "postgres": "postgres:16",
    "redis": "redis:7-alpine",
    "qdrant": "qdrant/qdrant:v1.17",
}


def _load_compose_images() -> dict[str, str]:
    """Load service image map from compose file with conservative fallbacks."""
    try:
        raw = yaml.safe_load(_COMPOSE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    services = raw.get("services", {}) if isinstance(raw, dict) else {}
    if not isinstance(services, dict):
        return {}

    images: dict[str, str] = {}
    for service_name, service_config in services.items():
        if not isinstance(service_config, dict):
            continue
        image = service_config.get("image")
        if isinstance(image, str) and image.strip() != "":
            images[service_name] = image.strip()
    return images


_COMPOSE_IMAGES = _load_compose_images()


def _service_image(service_name: str) -> str:
    """Resolve image for one service from compose, then built-in defaults."""
    return _COMPOSE_IMAGES.get(service_name, _IMAGE_DEFAULTS[service_name])


@dataclass(frozen=True, slots=True)
class RunningContainer:
    """Lightweight handle for a running temporary Docker container."""

    container_id: str
    host: str
    port: int


def _run_command(*args: str) -> subprocess.CompletedProcess[str]:
    """Execute one command and return captured stdout/stderr."""
    return subprocess.run(
        args,
        check=True,
        capture_output=True,
        text=True,
    )


def _docker_available() -> bool:
    """Return True when docker CLI is callable in the current environment."""
    try:
        _run_command("docker", "version")
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False
    return True


def _parse_published_port(port_output: str) -> tuple[str, int]:
    """Parse ``docker port`` output into host and integer port."""
    line = port_output.strip().splitlines()[0].strip()
    host, port = line.rsplit(":", maxsplit=1)
    return host, int(port)


def _wait_for_tcp(host: str, port: int, *, timeout_seconds: float = 30.0) -> None:
    """Wait until one TCP endpoint accepts a connection or time out."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError(f"timed out waiting for TCP endpoint {host}:{port}")


def _wait_for_postgres_ready(
    *,
    container_id: str,
    host: str,
    port: int,
    username: str,
    password: str,
    database: str,
    timeout_seconds: float = 60.0,
) -> None:
    """Wait until Postgres accepts stable SQL connections."""
    deadline = time.monotonic() + timeout_seconds
    quoted_password = quote_plus(password)
    dsn = f"postgresql+psycopg://{username}:{quoted_password}@{host}:{port}/{database}"
    while time.monotonic() < deadline:
        # First gate on in-container readiness probe.
        result = subprocess.run(
            (
                "docker",
                "exec",
                container_id,
                "pg_isready",
                "-U",
                username,
                "-d",
                database,
            ),
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            time.sleep(0.2)
            continue

        # Then verify host-side SQL connectivity to avoid startup races.
        try:
            engine = create_engine(dsn, pool_pre_ping=True)
            try:
                with engine.connect() as conn:
                    conn.exec_driver_sql("SELECT 1")
            finally:
                engine.dispose()
            return
        except Exception:  # noqa: BLE001
            time.sleep(0.2)
            continue
        time.sleep(0.2)
    raise TimeoutError("timed out waiting for Postgres readiness")


def _start_container(
    *,
    image: str,
    container_port: int,
    env: dict[str, str] | None = None,
) -> RunningContainer:
    """Start one detached ``docker run`` container and return mapped endpoint."""
    env_args: list[str] = []
    for key, value in (env or {}).items():
        env_args.extend(["--env", f"{key}={value}"])
    run_result = _run_command(
        "docker",
        "run",
        "--detach",
        "--rm",
        "--publish",
        f"127.0.0.1::{container_port}",
        *env_args,
        image,
    )
    container_id = run_result.stdout.strip()
    port_result = _run_command("docker", "port", container_id, f"{container_port}/tcp")
    host, port = _parse_published_port(port_result.stdout)
    _wait_for_tcp(host, port)
    return RunningContainer(container_id=container_id, host=host, port=port)


def _stop_container(container_id: str) -> None:
    """Stop one running container and ignore teardown-time failures."""
    subprocess.run(
        ("docker", "stop", container_id),
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="session")
def postgres_dsn() -> Iterator[str]:
    """Yield one temporary Postgres DSN for integration tests."""
    if not real_provider_tests_enabled():
        pytest.skip("real-provider integration tests disabled")
    if not _docker_available():
        pytest.skip("docker unavailable for integration tests")
    container = _start_container(
        image=_service_image("postgres"),
        container_port=5432,
        env={
            "POSTGRES_USER": "brain",
            "POSTGRES_PASSWORD": "brain",
            "POSTGRES_DB": "brain",
        },
    )
    _wait_for_postgres_ready(
        container_id=container.container_id,
        host=container.host,
        port=container.port,
        username="brain",
        password="brain",
        database="brain",
    )
    try:
        yield f"postgresql+psycopg://brain:brain@{container.host}:{container.port}/brain"
    finally:
        _stop_container(container.container_id)


@pytest.fixture(scope="session")
def integration_settings(postgres_dsn: str) -> CoreRuntimeSettings:
    """Yield settings object bound to temporary Postgres for repository tests."""
    return CoreRuntimeSettings(
        core=CoreSettings(),
        resources=ResourcesSettings(
            substrate={"postgres": {"url": postgres_dsn}}  # type: ignore[arg-type]
        ),
    )


@pytest.fixture(scope="session")
def migrated_integration_settings(
    integration_settings: CoreRuntimeSettings,
) -> CoreRuntimeSettings:
    """Run service migrations against temporary Postgres and return settings."""
    postgres_url = resolve_postgres_settings(integration_settings).url
    if postgres_url == "":
        raise RuntimeError("temporary integration Postgres URL is required")

    previous = os.environ.get("BRAIN_RESOURCES_SUBSTRATE__POSTGRES__URL")
    os.environ["BRAIN_RESOURCES_SUBSTRATE__POSTGRES__URL"] = postgres_url
    try:
        run_startup_migrations(settings=integration_settings)
    finally:
        if previous is None:
            os.environ.pop("BRAIN_RESOURCES_SUBSTRATE__POSTGRES__URL", None)
        else:
            os.environ["BRAIN_RESOURCES_SUBSTRATE__POSTGRES__URL"] = previous
    return integration_settings


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    """Yield one temporary Redis URL for integration tests."""
    if not real_provider_tests_enabled():
        pytest.skip("real-provider integration tests disabled")
    if not _docker_available():
        pytest.skip("docker unavailable for integration tests")
    container = _start_container(
        image=_service_image("redis"),
        container_port=6379,
    )
    try:
        yield f"redis://{container.host}:{container.port}/0"
    finally:
        _stop_container(container.container_id)


@pytest.fixture(scope="session")
def qdrant_url() -> Iterator[str]:
    """Yield one temporary Qdrant URL for integration tests."""
    if not real_provider_tests_enabled():
        pytest.skip("real-provider integration tests disabled")
    if not _docker_available():
        pytest.skip("docker unavailable for integration tests")
    container = _start_container(
        image=_service_image("qdrant"),
        container_port=6333,
    )
    try:
        yield f"http://{container.host}:{container.port}"
    finally:
        _stop_container(container.container_id)
