"""Built-in default configuration values for Brain services.

These defaults are the final fallback in the configuration cascade:
CLI params > ENV vars > config file > built-in defaults.

Defaults intentionally remain minimal and broadly safe so each service can
override or extend domain-specific configuration in its own package.
"""

from __future__ import annotations

from typing import Any

BUILTIN_DEFAULTS: dict[str, Any] = {
    "logging": {
        "level": "INFO",
        "json_output": True,
        "service": "brain",
        "environment": "dev",
    },
    "postgres": {
        "url": "postgresql+psycopg://brain:brain@postgres:5432/brain",
        "pool_size": 5,
        "max_overflow": 10,
        "pool_timeout_seconds": 30.0,
        "connect_timeout_seconds": 10.0,
        "sslmode": "prefer",
    },
    "embedding": {
        "request_timeout_seconds": 10.0,
        "default_top_k": 10,
        "max_top_k": 100,
        "namespace_strategy": "single_collection",
        "collection_name": "brain_embeddings",
        "distance_metric": "cosine",
        "qdrant_url": "http://qdrant:6333",
        "model_dimensions": {},
    },
}
