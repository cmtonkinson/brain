"""Pydantic settings for the Valkey substrate component."""

from __future__ import annotations

import os
from urllib.parse import quote_plus

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from lib.shared.config import CoreRuntimeSettings, resolve_component_settings
from resources.substrates.valkey.component import RESOURCE_COMPONENT_ID


class ValkeySettings(BaseModel):
    """Valkey connectivity and runtime defaults for cache and queue operations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str | None = "valkey://valkey:6379/0"
    host: str = "valkey"
    port: int = Field(default=6379, gt=0)
    db: int = Field(default=0, ge=0)
    username: str | None = None
    password: str | None = None
    password_env: str = ""
    ssl: bool = False
    connect_timeout_seconds: float = Field(default=5.0, gt=0)
    socket_timeout_seconds: float = Field(default=5.0, gt=0)
    health_timeout_seconds: float = Field(default=1.0, gt=0)
    max_connections: int = Field(default=20, gt=0)

    @field_validator("url", mode="before")
    @classmethod
    def _reject_empty_url(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() == "":
            raise ValueError(
                "substrate.valkey.url must not be empty; use None for split-field mode"
            )
        return value

    @model_validator(mode="after")
    def _resolve_fields(self) -> "ValkeySettings":
        """Resolve URL/password from split fields."""
        if self.url is not None:
            object.__setattr__(self, "url", self.url.strip())
            return self

        resolved_password = _resolve_password(
            password=self.password, password_env=self.password_env
        )
        object.__setattr__(self, "password", resolved_password)
        object.__setattr__(self, "url", _build_valkey_url_from_parts(self))
        return self


def _resolve_password(*, password: str | None, password_env: str) -> str | None:
    """Resolve password from inline value or environment variable reference."""
    env_name = password_env.strip()
    if password is not None and env_name != "":
        raise ValueError(
            "substrate.valkey.password and password_env are mutually exclusive"
        )
    if password is not None:
        return password
    if env_name == "":
        return None

    resolved = os.environ.get(env_name, "").strip()
    if resolved == "":
        raise ValueError(
            f"substrate.valkey.password_env references missing env var '{env_name}'"
        )
    return resolved


def _build_valkey_url_from_parts(valkey: ValkeySettings) -> str:
    """Construct Valkey URL from split fields when explicit URL is unset."""
    host = valkey.host.strip()
    if host == "":
        raise ValueError("substrate.valkey.host is required when url is unset")

    auth = ""
    username = valkey.username
    password = valkey.password
    if username is not None:
        auth = quote_plus(username)
        if password is not None:
            auth += f":{quote_plus(password)}"
        auth += "@"
    elif password is not None:
        auth = f":{quote_plus(password)}@"

    scheme = "valkeys" if valkey.ssl else "valkey"
    return f"{scheme}://{auth}{host}:{valkey.port}/{valkey.db}"


def resolve_valkey_settings(settings: CoreRuntimeSettings) -> ValkeySettings:
    """Resolve Valkey substrate settings from ``substrate.valkey``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(RESOURCE_COMPONENT_ID),
        model=ValkeySettings,
    )
