# Configuration Reference
This document describes Brain's configuration system: how settings are loaded,
where they live, and what every key does.

Primary config is `~/.config/brain/brain.yaml`. An optional secondary config
file, `~/.config/brain/secrets.yaml`, can hold sensitive overrides. A sample
with all defaults is at `config/brain.yaml.sample` in the repository.

------------------------------------------------------------------------
## Precedence Cascade
Settings are resolved in this order (highest wins):

1. **CLI parameters** — passed programmatically at process startup
2. **Environment variables** — prefixed with `BRAIN_`, `__`-separated for nesting
3. **Secrets config file** — `~/.config/brain/secrets.yaml` (if present)
4. **Config file** — `~/.config/brain/brain.yaml`
5. **Model defaults** — defined in each settings model (`packages/brain_shared/config/models.py`
   for global settings; component-local `config.py` modules for component
   settings)

`secrets.yaml` is loaded after `brain.yaml`, so only keys present in
`secrets.yaml` override `brain.yaml`; all other values still come from
`brain.yaml` (then defaults).

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
BRAIN_PROFILE__OPERATOR__SIGNAL_CONTACT_E164=+12025550100
BRAIN_PROFILE__DEFAULT_DIAL_CODE=+1
BRAIN_PROFILE__WEBHOOK_SHARED_SECRET=replace-me
BRAIN_COMPONENTS__SUBSTRATE__POSTGRES__URL=postgresql+psycopg://user:pass@host:5432/db
BRAIN_COMPONENTS__CORE_BOOT__BOOT_RETRY_ATTEMPTS=5
BRAIN_COMPONENTS__CORE_GRPC__BIND_PORT=50051
BRAIN_COMPONENTS__CORE_GRPC__ENABLE_REFLECTION=true
BRAIN_COMPONENTS__CORE_HEALTH__MAX_TIMEOUT_SECONDS=1.0
BRAIN_COMPONENTS__SUBSTRATE__POSTGRES__POOL_SIZE=10
BRAIN_COMPONENTS__SUBSTRATE__QDRANT__URL=http://qdrant:6333
BRAIN_COMPONENTS__SUBSTRATE__REDIS__URL=redis://redis:6379/0
BRAIN_COMPONENTS__ADAPTER__FILESYSTEM__ROOT_DIR=/var/lib/brain/blobs
BRAIN_COMPONENTS__SERVICE__EMBEDDING_AUTHORITY__MAX_LIST_LIMIT=1000
BRAIN_COMPONENTS__SERVICE__CACHE_AUTHORITY__DEFAULT_TTL_SECONDS=600
BRAIN_COMPONENTS__SERVICE__MEMORY_AUTHORITY__DIALOGUE_RECENT_TURNS=12
BRAIN_COMPONENTS__SERVICE__OBJECT_AUTHORITY__MAX_BLOB_SIZE_BYTES=10485760
BRAIN_COMPONENTS__ADAPTER__LITELLM__BASE_URL=http://litellm:4000
BRAIN_COMPONENTS__ADAPTER__SIGNAL__BASE_URL=http://signal-api:8080
BRAIN_COMPONENTS__SERVICE__LANGUAGE_MODEL__STANDARD__MODEL=gpt-oss:20b
BRAIN_COMPONENTS__SERVICE__SWITCHBOARD__QUEUE_NAME=signal_inbound
BRAIN_COMPONENTS__SERVICE__SWITCHBOARD__WEBHOOK_BIND_PORT=8091
BRAIN_COMPONENTS__SERVICE__SWITCHBOARD__WEBHOOK_PUBLIC_BASE_URL=https://brain.example.com
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
## `profile`
Root profile and operator identity settings.

| Key | Default | Description |
|---|---|---|
| `operator.signal_contact_e164` | `+10000000000` | Canonical operator Signal identity used by Switchboard ingress policy. Replace with the real operator E.164 number. |
| `default_dial_code` | `+1` | Switchboard fallback dial code for non-E.164 operator/sender values (for example `+1`, `+44`). |
| `webhook_shared_secret` | `replace-me` | Shared secret used for inbound webhook signature verification. Replace for any non-local environment. |

------------------------------------------------------------------------
## `components`
Component-local settings grouped under `components.service`,
`components.adapter`, and `components.substrate`. Each component owns its
Pydantic model, defaults, and validation rules.

### `components.core_boot`
Core boot framework orchestration settings.

| Key | Default | Description |
|---|---|---|
| `readiness_poll_interval_seconds` | `0.25` | Interval between readiness probes while waiting for dependencies. Must be > 0. |
| `readiness_timeout_seconds` | `30.0` | Maximum time to wait for one hook readiness probe to return true. Must be > 0. |
| `boot_retry_attempts` | `3` | Maximum attempts to execute one hook's `boot()` function before fail-hard abort. Must be > 0. |
| `boot_retry_delay_seconds` | `0.5` | Delay between `boot()` retry attempts after failures. Must be >= 0. |
| `boot_timeout_seconds` | `30.0` | Maximum allowed runtime for one successful `boot()` invocation. Must be > 0. |

### `components.core_grpc`
Core gRPC runtime bind settings.

| Key | Default | Description |
|---|---|---|
| `bind_host` | `0.0.0.0` | Bind host for the Brain Core gRPC server. |
| `bind_port` | `50051` | Bind port for the Brain Core gRPC server. Must be in `1..65535`. |
| `enable_reflection` | `false` | Enable gRPC Server Reflection for runtime method/service introspection tools (for example `grpcurl`, Postman gRPC browser). |

### `components.core_health`
Core aggregate health policy settings.

| Key | Default | Description |
|---|---|---|
| `max_timeout_seconds` | `1.0` | Global maximum duration for any service/resource `health()` call. If exceeded, that component is unhealthy by definition. Must be > 0. |

### `components.substrate.postgres`
PostgreSQL substrate connection settings.

| Key | Default | Description |
|---|---|---|
| `url` | `postgresql+psycopg://brain:brain@postgres:5432/brain` | SQLAlchemy-style connection URL. Override with `BRAIN_COMPONENTS__SUBSTRATE__POSTGRES__URL`. |
| `pool_size` | `5` | Number of persistent connections in the pool. |
| `max_overflow` | `10` | Extra connections allowed above `pool_size` under load. |
| `pool_timeout_seconds` | `30.0` | Seconds to wait for a connection from the pool before raising. |
| `pool_pre_ping` | `true` | Test connections with a lightweight query before use (detects stale connections). |
| `connect_timeout_seconds` | `10.0` | Seconds to wait when establishing a new connection. |
| `health_timeout_seconds` | `1.0` | Timeout budget in seconds for Postgres health probes. Must be > 0. |
| `sslmode` | `prefer` | PostgreSQL SSL mode (`disable`, `allow`, `prefer`, `require`, `verify-ca`, `verify-full`). |
| `host` | `postgres` | Hostname used when `url` is unset. |
| `port` | `5432` | Port used when `url` is unset. |
| `database` | `brain` | Database used when `url` is unset. |
| `user` | `brain` | Username used when `url` is unset. |
| `password` | `brain` | Password used when `url` is unset. |

### `components.substrate.qdrant`
Qdrant substrate defaults.

| Key | Default | Description |
|---|---|---|
| `url` | `http://qdrant:6333` | Base URL of the Qdrant vector search instance. |
| `distance_metric` | `cosine` | Vector distance metric. One of `cosine`, `dot`, `euclid`. |
| `request_timeout_seconds` | `10.0` | Per-request timeout for Qdrant operations. Must be > 0. |

### `components.substrate.redis`
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
| `health_timeout_seconds` | `1.0` | Timeout budget in seconds for Redis health probes. Must be > 0. |
| `max_connections` | `20` | Maximum client pool connections. Must be > 0. |

### `components.substrate.filesystem`
Filesystem substrate defaults for OAS blob persistence.

| Key | Default | Description |
|---|---|---|
| `root_dir` | `./var/blobs` | Root directory where blob files are persisted. |
| `temp_prefix` | `blobtmp` | Prefix used for temporary files created during atomic writes. |
| `fsync_writes` | `true` | When `true`, fsync temp files before atomic replace. |
| `default_extension` | `blob` | Default extension used when OAS put requests omit extension. |

### `components.adapter.litellm`
LiteLLM adapter connection defaults.

| Key | Default | Description |
|---|---|---|
| `base_url` | `http://litellm:4000` | Base URL for LiteLLM gateway HTTP endpoints. |
| `api_key` | `""` | Optional API token sent as `Authorization: Bearer <token>`. |
| `timeout_seconds` | `30.0` | Per-request HTTP timeout. Must be > 0. |
| `max_retries` | `2` | Number of retries for dependency-style failures (network/5xx). Must be >= 0. |

### `components.substrate.obsidian`
Obsidian Local REST API substrate defaults.

| Key | Default | Description |
|---|---|---|
| `base_url` | `http://host.docker.internal:27123` | Base URL for the Obsidian Local REST API instance. |
| `api_key` | `""` | Optional API token sent as `Authorization: Bearer <token>`. |
| `timeout_seconds` | `10.0` | Per-request HTTP timeout in seconds. Must be > 0. |
| `max_retries` | `2` | Number of retries for dependency-style failures (network/5xx/429). Must be >= 0. |

### `components.adapter.signal`
Signal runtime adapter defaults.

| Key | Default | Description |
|---|---|---|
| `base_url` | `http://signal-api:8080` | Base URL for Signal runtime receive/health endpoints. |
| `receive_e164` | `+10000000000` | E.164 identity polled for inbound messages via `/v1/receive/{number}`. |
| `health_timeout_seconds` | `1.0` | Per-request timeout in seconds for Signal health probes. Must be > 0. |
| `timeout_seconds` | `10.0` | Per-request HTTP timeout in seconds. Must be > 0. |
| `max_retries` | `2` | Number of retries for dependency-style failures (network/5xx). Must be >= 0. |
| `poll_interval_seconds` | `1.0` | Steady-state delay between successful polling cycles. Must be > 0. |
| `poll_receive_timeout_seconds` | `5` | Timeout argument passed to `/v1/receive/{number}` long-poll calls. Must be >= 1. |
| `poll_max_messages` | `10` | Maximum messages requested per receive poll call. Must be >= 1. |
| `failure_backoff_initial_seconds` | `1.0` | Initial delay after poll/forward failure before retry. Must be > 0. |
| `failure_backoff_max_seconds` | `30.0` | Maximum capped delay for failure backoff. Must be > 0. |
| `failure_backoff_multiplier` | `2.0` | Exponential multiplier applied to each consecutive failure delay. Must be > 1.0. |
| `failure_backoff_jitter_ratio` | `0.2` | Symmetric random jitter ratio applied to failure delays. Must be in `[0,1)`. |

### `components.service.embedding_authority`
Embedding Authority Service runtime settings.

| Key | Default | Description |
|---|---|---|
| `max_list_limit` | `500` | Maximum number of results returned by list operations. Must be > 0. |

### `components.service.cache_authority`
Cache Authority Service runtime settings.

| Key | Default | Description |
|---|---|---|
| `key_prefix` | `brain` | Non-empty prefix used for Redis key and queue namespacing. |
| `default_ttl_seconds` | `300` | Default TTL applied when `set_value` is called without explicit TTL. Must be > 0. |
| `allow_non_expiring_keys` | `true` | When `true`, `ttl_seconds=0` is allowed and maps to non-expiring keys. |

### `components.service.memory_authority`
Memory Authority Service runtime settings.

| Key | Default | Description |
|---|---|---|
| `dialogue_recent_turns` | `10` | Number of recent dialogue turns included verbatim in assembled context. Must be > 0. |
| `dialogue_older_turns` | `20` | Maximum number of older turns considered for summarized dialogue context. Must be >= 0. |
| `focus_token_budget` | `512` | Hard token ceiling for session focus content. Must be > 0. |
| `profile.operator_name` | `Operator` | Operator display name injected into profile context. |
| `profile.brain_name` | `Brain` | Brain display name injected into profile context. |
| `profile.brain_verbosity` | `normal` | Profile verbosity selector. One of `terse`, `normal`, `verbose`. |

### `components.service.object_authority`
Object Authority Service runtime settings.

| Key | Default | Description |
|---|---|---|
| `digest_algorithm` | `sha256` | Digest algorithm used for object key generation. Currently only `sha256` is supported. |
| `digest_version` | `b1` | Object key version prefix used in canonical object keys. |
| `max_blob_size_bytes` | `52428800` | Maximum accepted blob payload size in bytes for `put_object`. Must be > 0. |

### `components.service.vault_authority`
Vault Authority Service runtime settings.

| Key | Default | Description |
|---|---|---|
| `max_list_limit` | `500` | Maximum list operation limit accepted by VAS. Must be > 0. |
| `max_search_limit` | `200` | Maximum lexical search result limit accepted by VAS. Must be > 0. |

### `components.service.language_model`
Language Model Service profile settings.

| Key | Default | Description |
|---|---|---|
| `embedding.provider` | `ollama` | Provider used for embedding generation requests. |
| `embedding.model` | `mxbai-embed-large` | Model identifier used for embedding generation requests. |
| `quick.provider` | `""` | Optional quick provider override; falls back to `standard.provider` when unset/blank. |
| `quick.model` | `""` | Optional quick model override; falls back to `standard.model` when unset/blank. |
| `standard.provider` | `ollama` | Standard chat provider used for standard requests and fallback resolution. |
| `standard.model` | `gpt-oss:20b` | Standard chat model used for standard requests and fallback resolution. |
| `deep.provider` | `""` | Optional deep provider override; falls back to `standard.provider` when unset/blank. |
| `deep.model` | `""` | Optional deep model override; falls back to `standard.model` when unset/blank. |

### `components.service.switchboard`
Switchboard Service runtime settings.

| Key | Default | Description |
|---|---|---|
| `queue_name` | `signal_inbound` | CAS queue name used for accepted inbound Signal events. |
| `signature_tolerance_seconds` | `300` | Allowed absolute clock skew when validating webhook timestamps. Must be >= 0. |
| `webhook_bind_host` | `0.0.0.0` | Bind host for the Switchboard inbound webhook HTTP server. |
| `webhook_bind_port` | `8091` | Bind port for the Switchboard inbound webhook HTTP server. Must be in `1..65535`. |
| `webhook_path` | `/v1/inbound/signal/webhook` | Absolute callback path served by Switchboard webhook ingress. |
| `webhook_public_base_url` | `http://127.0.0.1:8091` | Publicly reachable base URL used to construct callback registration target. |
| `webhook_register_max_retries` | `8` | Number of boot-time retry attempts after initial callback registration try when dependencies are not ready. Must be >= 0. |
| `webhook_register_retry_delay_seconds` | `2.0` | Delay between callback registration retries during boot. Must be > 0. |

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
