"""Pydantic settings for the Redis substrate component."""

from __future__ import annotations

import os
from urllib.parse import quote_plus

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.brain_shared.config import CoreRuntimeSettings, resolve_component_settings
from resources.substrates.redis.component import RESOURCE_COMPONENT_ID


class RedisSettings(BaseModel):
    """Redis connectivity and runtime defaults for cache and queue operations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str | None = "redis://redis:6379/0"
    host: str = "redis"
    port: int = Field(default=6379, gt=0)
    db: int = Field(default=0, ge=0)
    username: str = ""
    password: str = ""
    password_env: str = ""
    ssl: bool = False
    connect_timeout_seconds: float = Field(default=5.0, gt=0)
    socket_timeout_seconds: float = Field(default=5.0, gt=0)
    health_timeout_seconds: float = Field(default=1.0, gt=0)
    max_connections: int = Field(default=20, gt=0)

    @model_validator(mode="after")
    def _resolve_fields(self) -> "RedisSettings":
        """Resolve URL/password from split fields."""
        if self.url is not None and self.url.strip() != "":
            object.__setattr__(self, "url", self.url.strip())
            return self

        resolved_password = _resolve_password(
            password=self.password, password_env=self.password_env
        )
        object.__setattr__(self, "password", resolved_password)
        object.__setattr__(self, "url", _build_redis_url_from_parts(self))
        return self


def _resolve_password(*, password: str, password_env: str) -> str:
    """Resolve password from inline value or environment variable reference."""
    inline = password.strip()
    env_name = password_env.strip()
    if inline != "" and env_name != "":
        raise ValueError(
            "substrate.redis.password and password_env are mutually exclusive"
        )
    if inline != "":
        return inline
    if env_name == "":
        return ""

    resolved = os.environ.get(env_name, "").strip()
    if resolved == "":
        raise ValueError(
            f"substrate.redis.password_env references missing env var '{env_name}'"
        )
    return resolved


def _build_redis_url_from_parts(redis: RedisSettings) -> str:
    """Construct Redis URL from split fields when explicit URL is unset."""
    host = redis.host.strip()
    if host == "":
        raise ValueError("substrate.redis.host is required when url is unset")

    auth = ""
    username = redis.username.strip()
    password = redis.password.strip()
    if username != "":
        auth = quote_plus(username)
        if password != "":
            auth += f":{quote_plus(password)}"
        auth += "@"
    elif password != "":
        auth = f":{quote_plus(password)}@"

    scheme = "rediss" if redis.ssl else "redis"
    return f"{scheme}://{auth}{host}:{redis.port}/{redis.db}"


def resolve_redis_settings(settings: CoreRuntimeSettings) -> RedisSettings:
    """Resolve Redis substrate settings from ``substrate.redis``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(RESOURCE_COMPONENT_ID),
        model=RedisSettings,
    )
