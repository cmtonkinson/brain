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
BRAIN_COMPONENTS__SUBSTRATE_REDIS__URL=redis://redis:6379/0
BRAIN_COMPONENTS__ADAPTER_FILESYSTEM__ROOT_DIR=/var/lib/brain/blobs
BRAIN_COMPONENTS__SERVICE_EMBEDDING_AUTHORITY__MAX_LIST_LIMIT=1000
BRAIN_COMPONENTS__SERVICE_CACHE_AUTHORITY__DEFAULT_TTL_SECONDS=600
BRAIN_COMPONENTS__SERVICE_OBJECT_AUTHORITY__MAX_BLOB_SIZE_BYTES=10485760
BRAIN_COMPONENTS__ADAPTER_LITELLM__BASE_URL=http://litellm:4000
BRAIN_COMPONENTS__SERVICE_LANGUAGE_MODEL__CHAT_DEFAULT__MODEL=gpt-oss
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

### `components.substrate_redis`
Redis substrate connection defaults.

| Key | Default | Description |
|---|---|---|
| `url` | `redis://redis:6379/0` | Redis URL. When non-empty, this is authoritative and split fields are ignored for URL construction. |
| `host` | `redis` | Hostname used when `url` is unset/blank and split-field URL mode is used. |
| `port` | `6379` | Port used when split-field URL mode is used. Must be > 0. |
| `db` | `0` | Redis logical database index used when split-field URL mode is used. Must be >= 0. |
| `username` | `""` | Optional Redis username for split-field URL mode. |
| `password` | `""` | Optional inline Redis password for split-field URL mode. Mutually exclusive with `password_env`. |
| `password_env` | `""` | Optional environment variable name containing Redis password for split-field URL mode. |
| `ssl` | `false` | Use TLS (`rediss://`) in split-field URL mode. |
| `connect_timeout_seconds` | `5.0` | Socket connect timeout in seconds. Must be > 0. |
| `socket_timeout_seconds` | `5.0` | Socket operation timeout in seconds. Must be > 0. |
| `max_connections` | `20` | Maximum client pool connections. Must be > 0. |

### `components.adapter_filesystem`
Filesystem adapter defaults for OAS blob persistence.

| Key | Default | Description |
|---|---|---|
| `root_dir` | `./var/blobs` | Root directory where blob files are persisted. |
| `temp_prefix` | `blobtmp` | Prefix used for temporary files created during atomic writes. |
| `fsync_writes` | `true` | When `true`, fsync temp files before atomic replace. |
| `default_extension` | `blob` | Default extension used when OAS put requests omit extension. |

### `components.adapter_litellm`
LiteLLM adapter connection defaults.

| Key | Default | Description |
|---|---|---|
| `base_url` | `http://litellm:4000` | Base URL for LiteLLM gateway HTTP endpoints. |
| `api_key` | `""` | Optional API token sent as `Authorization: Bearer <token>`. |
| `timeout_seconds` | `30.0` | Per-request HTTP timeout. Must be > 0. |
| `max_retries` | `2` | Number of retries for dependency-style failures (network/5xx). Must be >= 0. |

### `components.adapter_obsidian`
Obsidian Local REST API adapter defaults.

| Key | Default | Description |
|---|---|---|
| `base_url` | `http://127.0.0.1:27124` | Base URL for the Obsidian Local REST API instance. |
| `api_key` | `""` | Optional API token sent as `Authorization: Bearer <token>`. |
| `timeout_seconds` | `10.0` | Per-request HTTP timeout in seconds. Must be > 0. |
| `max_retries` | `2` | Number of retries for dependency-style failures (network/5xx/429). Must be >= 0. |

### `components.service_embedding_authority`
Embedding Authority Service runtime settings.

| Key | Default | Description |
|---|---|---|
| `max_list_limit` | `500` | Maximum number of results returned by list operations. Must be > 0. |

### `components.service_cache_authority`
Cache Authority Service runtime settings.

| Key | Default | Description |
|---|---|---|
| `key_prefix` | `brain` | Non-empty prefix used for Redis key and queue namespacing. |
| `default_ttl_seconds` | `300` | Default TTL applied when `set_value` is called without explicit TTL. Must be > 0. |
| `allow_non_expiring_keys` | `true` | When `true`, `ttl_seconds=0` is allowed and maps to non-expiring keys. |

### `components.service_object_authority`
Object Authority Service runtime settings.

| Key | Default | Description |
|---|---|---|
| `digest_algorithm` | `sha256` | Digest algorithm used for object key generation. Currently only `sha256` is supported. |
| `digest_version` | `b1` | Object key version prefix used in canonical object keys. |
| `max_blob_size_bytes` | `52428800` | Maximum accepted blob payload size in bytes for `put_object`. Must be > 0. |

### `components.service_vault_authority`
Vault Authority Service runtime settings.

| Key | Default | Description |
|---|---|---|
| `max_list_limit` | `500` | Maximum list operation limit accepted by VAS. Must be > 0. |
| `max_search_limit` | `200` | Maximum lexical search result limit accepted by VAS. Must be > 0. |

### `components.service_language_model`
Language Model Service profile settings.

| Key | Default | Description |
|---|---|---|
| `embedding.provider` | `ollama` | Provider used for embedding generation requests. |
| `embedding.model` | `mxbai-embed-large` | Model identifier used for embedding generation requests. |
| `chat_default.provider` | `ollama` | Default provider used for chat requests. |
| `chat_default.model` | `gpt-oss` | Default model identifier used for chat requests. |
| `chat_advanced.provider` | `""` | Optional advanced provider override; falls back to `chat_default.provider` when unset. |
| `chat_advanced.model` | `""` | Optional advanced model override; falls back to `chat_default.model` when unset. |

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
