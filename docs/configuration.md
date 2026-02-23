# Configuration Reference
This document describes Brain's configuration system: how settings are loaded,
where they live, and what every key does.

The config file for a running Brain is `~/.config/brain/brain.yaml`. A sample
with all defaults is at `config/brain.yaml.sample` in the repository.

------------------------------------------------------------------------
## Precedence Cascade
Settings are resolved in this order (highest wins):

1. **CLI parameters** — passed programmatically at process startup
2. **Environment variables** — prefixed with `BRAIN_`, `__`-separated for nesting
3. **Config file** — `~/.config/brain/brain.yaml`
4. **Model defaults** — defined in each settings model (`packages/brain_shared/config/models.py`
   for global settings; component-local `config.py` modules for component
   settings)

Configuration models follow the canonical Pydantic contract rules in
[Conventions](conventions.md).

### Environment Variable Format
Any config key can be set via environment variable:
- Prefix: `BRAIN_`
- Nested keys: use `__` as the separator
- Values are coerced: `true`/`false` → bool, integers → int, floats → float,
  JSON objects/arrays → parsed, `null`/`none` → `None`

Examples:
```
BRAIN_LOGGING__LEVEL=DEBUG
BRAIN_COMPONENTS__SUBSTRATE_POSTGRES__URL=postgresql+psycopg://user:pass@host:5432/db
BRAIN_COMPONENTS__SUBSTRATE_POSTGRES__POOL_SIZE=10
BRAIN_COMPONENTS__SUBSTRATE_QDRANT__URL=http://localhost:6333
BRAIN_COMPONENTS__SERVICE_EMBEDDING_AUTHORITY__MAX_LIST_LIMIT=1000
```

------------------------------------------------------------------------
## `logging`
Controls structured log output.

| Key | Default | Description |
|---|---|---|
| `level` | `INFO` | Log level. One of `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `json_output` | `true` | Emit logs as JSON. Set `false` for human-readable output during local development. |
| `service` | `brain` | Service name tag attached to every log record. |
| `environment` | `dev` | Environment tag (`dev`, `staging`, `prod`, etc.) attached to every log record. |

------------------------------------------------------------------------
## `components`
Component-local settings keyed by `ComponentId`. Each component owns its
Pydantic model, defaults, and validation rules.

### `components.substrate_postgres`
PostgreSQL substrate connection settings.

| Key | Default | Description |
|---|---|---|
| `url` | `postgresql+psycopg://brain:brain@postgres:5432/brain` | SQLAlchemy-style connection URL. Override with `BRAIN_COMPONENTS__SUBSTRATE_POSTGRES__URL`. |
| `pool_size` | `5` | Number of persistent connections in the pool. |
| `max_overflow` | `10` | Extra connections allowed above `pool_size` under load. |
| `pool_timeout_seconds` | `30.0` | Seconds to wait for a connection from the pool before raising. |
| `pool_pre_ping` | `true` | Test connections with a lightweight query before use (detects stale connections). |
| `connect_timeout_seconds` | `10.0` | Seconds to wait when establishing a new connection. |
| `sslmode` | `prefer` | PostgreSQL SSL mode (`disable`, `allow`, `prefer`, `require`, `verify-ca`, `verify-full`). |
| `host` | `postgres` | Hostname used when `url` is unset. |
| `port` | `5432` | Port used when `url` is unset. |
| `database` | `brain` | Database used when `url` is unset. |
| `user` | `brain` | Username used when `url` is unset. |
| `password` | `brain` | Password used when `url` is unset. |

### `components.substrate_qdrant`
Qdrant substrate defaults.

| Key | Default | Description |
|---|---|---|
| `url` | `http://qdrant:6333` | Base URL of the Qdrant vector search instance. |
| `distance_metric` | `cosine` | Vector distance metric. One of `cosine`, `dot`, `euclid`. |
| `request_timeout_seconds` | `10.0` | Per-request timeout for Qdrant operations. Must be > 0. |

### `components.service_embedding_authority`
Embedding Authority Service runtime settings.

| Key | Default | Description |
|---|---|---|
| `max_list_limit` | `500` | Maximum number of results returned by list operations. Must be > 0. |

------------------------------------------------------------------------
## `observability`
OpenTelemetry metric and tracer names. These are advanced settings; the
defaults are correct for standard deployments and rarely need to change.

### `observability.public_api.otel`
| Key | Default | Description |
|---|---|---|
| `meter_name` | `brain.public_api` | OTel meter name for public API instrumentation. |
| `tracer_name` | `brain.public_api` | OTel tracer name for public API instrumentation. |
| `metric_public_api_calls_total` | `brain_public_api_calls_total` | Counter: total public API invocations. |
| `metric_public_api_duration_ms` | `brain_public_api_duration_ms` | Histogram: public API call duration in ms. |
| `metric_public_api_errors_total` | `brain_public_api_errors_total` | Counter: public API errors. |
| `metric_instrumentation_failures_total` | `brain_public_api_instrumentation_failures_total` | Counter: instrumentation-layer failures. |
| `metric_qdrant_ops_total` | `brain_qdrant_ops_total` | Counter: total Qdrant operations. |
| `metric_qdrant_op_duration_ms` | `brain_qdrant_op_duration_ms` | Histogram: Qdrant operation duration in ms. |

------------------------------------------------------------------------
_End of Configuration Reference_
