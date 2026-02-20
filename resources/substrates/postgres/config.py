"""Configuration model for shared Postgres substrate access."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import quote_plus


@dataclass(frozen=True)
class PostgresConfig:
    """Runtime settings for constructing Postgres clients and pools."""

    url: str
    pool_size: int
    max_overflow: int
    pool_timeout_seconds: float
    pool_pre_ping: bool
    connect_timeout_seconds: float
    sslmode: str

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> "PostgresConfig":
        """Build shared Postgres settings from merged app configuration."""
        postgres = config.get("postgres", {}) if isinstance(config, Mapping) else {}

        url = str(postgres.get("url", "")).strip()
        if not url:
            url = _build_url_from_parts(postgres)
        pool_pre_ping_raw = postgres.get("pool_pre_ping", True)

        instance = cls(
            url=url,
            pool_size=int(postgres.get("pool_size", 5)),
            max_overflow=int(postgres.get("max_overflow", 10)),
            pool_timeout_seconds=float(postgres.get("pool_timeout_seconds", 30.0)),
            pool_pre_ping=_coerce_bool(pool_pre_ping_raw),
            connect_timeout_seconds=float(
                postgres.get("connect_timeout_seconds", 10.0)
            ),
            sslmode=str(postgres.get("sslmode", "prefer")),
        )
        instance.validate()
        return instance

    def validate(self) -> None:
        """Validate Postgres settings required for reliable connectivity."""
        if not self.url:
            raise ValueError("postgres.url is required")
        if self.pool_size <= 0:
            raise ValueError("postgres.pool_size must be > 0")
        if self.max_overflow < 0:
            raise ValueError("postgres.max_overflow must be >= 0")
        if self.pool_timeout_seconds <= 0:
            raise ValueError("postgres.pool_timeout_seconds must be > 0")
        if self.connect_timeout_seconds <= 0:
            raise ValueError("postgres.connect_timeout_seconds must be > 0")
        if self.sslmode not in {
            "disable",
            "allow",
            "prefer",
            "require",
            "verify-ca",
            "verify-full",
        }:
            raise ValueError(
                "postgres.sslmode must be one of: disable, allow, prefer, require, verify-ca, verify-full"
            )


def _build_url_from_parts(postgres: Mapping[str, Any]) -> str:
    """Construct SQLAlchemy psycopg URL from split config values."""
    host = str(postgres.get("host", "postgres")).strip()
    port = int(postgres.get("port", 5432))
    database = str(postgres.get("database", "brain")).strip()
    user = str(postgres.get("user", "brain")).strip()
    password = str(postgres.get("password", "brain")).strip()

    if not host:
        raise ValueError("postgres.host is required when postgres.url is unset")
    if not database:
        raise ValueError("postgres.database is required when postgres.url is unset")
    if not user:
        raise ValueError("postgres.user is required when postgres.url is unset")

    return (
        "postgresql+psycopg://"
        f"{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{quote_plus(database)}"
    )


def _coerce_bool(value: object) -> bool:
    """Normalize boolean-like values from config sources."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return bool(value)
