"""Built-in default configuration values for Brain services.

These defaults are the final fallback in the configuration cascade:
CLI params > ENV vars > config file > built-in defaults.
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
        "pool_pre_ping": True,
        "connect_timeout_seconds": 10.0,
        "sslmode": "prefer",
    },
    "embedding": {
        "provider": "ollama",
        "name": "nomic-embed-text",
        "version": "v1",
        "dimensions": 768,
        "qdrant_url": "http://qdrant:6333",
        "distance_metric": "cosine",
        "request_timeout_seconds": 10.0,
        "max_list_limit": 500,
        "repair_batch_limit": 500,
    },
    "observability": {
        "public_api": {
            "otel": {
                "meter_name": "brain.public_api",
                "tracer_name": "brain.public_api",
                "metric_public_api_calls_total": "brain_public_api_calls_total",
                "metric_public_api_duration_ms": "brain_public_api_duration_ms",
                "metric_public_api_errors_total": "brain_public_api_errors_total",
                "metric_instrumentation_failures_total": "brain_public_api_instrumentation_failures_total",
                "metric_qdrant_ops_total": "brain_qdrant_ops_total",
                "metric_qdrant_op_duration_ms": "brain_qdrant_op_duration_ms",
            }
        }
    },
}
