# Configuration Reference
This document describes Brain's configuration system: how settings are loaded,
where they live, and what every key does.

Runtime configuration is split across:
- `~/.config/brain/core.yaml`
- `~/.config/brain/resources.yaml`
- `~/.config/brain/actors.yaml`

An optional `~/.config/brain/secrets.yaml` can hold sensitive overrides for any
of those files. Samples live in `config/*.yaml.sample` in the repository.

------------------------------------------------------------------------
## Precedence Cascade
Settings are resolved in this order (highest wins):

1. **CLI parameters** — passed programmatically at process startup
2. **Environment variables** — service-specific prefixes, `__`-separated for nesting
3. **Secrets config file** — `~/.config/brain/secrets.yaml` (if present)
4. **Config file** — one of `core.yaml`, `resources.yaml`, or `actors.yaml`
5. **Model defaults** — defined in `packages/brain_shared/config/models.py` and
   component-local `config.py` modules

`secrets.yaml` is loaded after the primary YAML file for each settings model, so
only keys present in `secrets.yaml` override the corresponding config file.

Configuration models follow the canonical Pydantic contract rules in
[Conventions](conventions.md).

### Environment Variable Format
Any config key can be set via environment variable:
- Prefixes:
  - `BRAIN_CORE_` for `core.yaml`
  - `BRAIN_RESOURCES_` for `resources.yaml`
  - `BRAIN_ACTORS_` for `actors.yaml`
- Nested keys: use `__` as the separator
- Values are coerced: `true`/`false` → bool, integers → int, floats → float,
  JSON objects/arrays → parsed, `null`/`none` → `None`

Examples:
```
BRAIN_CORE__LOGGING__LEVEL=DEBUG
BRAIN_CORE__PROFILE__OPERATOR__SIGNAL_CONTACT_E164=+12025550100
BRAIN_CORE__PROFILE__DEFAULT_DIAL_CODE=+1
BRAIN_CORE__PROFILE__WEBHOOK_SHARED_SECRET=replace-me
BRAIN_CORE__BOOT__BOOT_RETRY_ATTEMPTS=5
BRAIN_CORE__HTTP__HOST=0.0.0.0
BRAIN_CORE__HTTP__PORT=8898
BRAIN_CORE__HEALTH__MAX_TIMEOUT_SECONDS=1.0
BRAIN_RESOURCES__SUBSTRATE__POSTGRES__URL=postgresql+psycopg://user:pass@host:5432/db
BRAIN_RESOURCES__SUBSTRATE__POSTGRES__POOL_SIZE=10
BRAIN_RESOURCES__SUBSTRATE__QDRANT__URL=http://qdrant:6333
BRAIN_RESOURCES__SUBSTRATE__REDIS__URL=redis://redis:6379/0
BRAIN_RESOURCES__ADAPTER__LITELLM__BASE_URL=http://litellm:4000
BRAIN_RESOURCES_ADAPTER__SIGNAL__BASE_URL=http://signal-api:8080
BRAIN_ACTORS__CORE__HOST=127.0.0.1
BRAIN_ACTORS__CORE__PORT=8898
BRAIN_ACTORS__CORE__TIMEOUT_SECONDS=10.0
BRAIN_ACTORS__CLI__PRINCIPAL=operator
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
| `operator_name` | `Operator` | Operator display name injected into assembled memory context. |
| `brain_name` | `Brain` | Brain display name injected into assembled memory context. |
| `brain_verbosity` | `normal` | Context verbosity selector. One of `terse`, `normal`, `verbose`. |
| `system_prompt_append` | `null` | Optional operator-supplied text appended verbatim to the agent system prompt at startup. |

------------------------------------------------------------------------
## Runtime Settings Namespaces
Core runtime settings live under `core.*`. Component-local settings live under
`core.service`, `resources.adapter`, and `resources.substrate`. Each component
owns its Pydantic model, defaults, and validation rules.

### `core.boot`
Core boot framework orchestration settings.

| Key | Default | Description |
|---|---|---|
| `readiness_poll_interval_seconds` | `0.25` | Interval between readiness probes while waiting for dependencies. Must be > 0. |
| `readiness_timeout_seconds` | `30.0` | Maximum time to wait for one hook readiness probe to return true. Must be > 0. |
| `boot_retry_attempts` | `3` | Maximum attempts to execute one hook's `boot()` function before fail-hard abort. Must be > 0. |
| `boot_retry_delay_seconds` | `0.5` | Delay between `boot()` retry attempts after failures. Must be >= 0. |
| `boot_timeout_seconds` | `30.0` | Maximum allowed runtime for one successful `boot()` invocation. Must be > 0. |

### `core.http`
Core HTTP runtime settings.

| Key | Default | Description |
|---|---|---|
| `host` | `0.0.0.0` | Host interface for the Brain Core FastAPI runtime. |
| `port` | `8898` | TCP port for the Brain Core FastAPI runtime. |

### `core.health`
Core aggregate health policy settings.

| Key | Default | Description |
|---|---|---|
| `max_timeout_seconds` | `1.0` | Global maximum duration for any service/resource `health()` call. If exceeded, that component is unhealthy by definition. Must be > 0. |

### `resources.substrate.postgres`
PostgreSQL substrate connection settings.

| Key | Default | Description |
|---|---|---|
| `url` | `postgresql+psycopg://brain:brain@postgres:5432/brain` | SQLAlchemy-style connection URL. Override with `BRAIN_RESOURCES__SUBSTRATE__POSTGRES__URL`. |
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

### `resources.substrate.qdrant`
Qdrant substrate defaults.

| Key | Default | Description |
|---|---|---|
| `url` | `http://qdrant:6333` | Base URL of the Qdrant vector search instance. |
| `distance_metric` | `cosine` | Vector distance metric. One of `cosine`, `dot`, `euclid`. |
| `request_timeout_seconds` | `10.0` | Per-request timeout for Qdrant operations. Must be > 0. |

### `resources.substrate.redis`
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

### `resources.substrate.filesystem`
Filesystem substrate defaults for OAS blob persistence.

| Key | Default | Description |
|---|---|---|
| `root_dir` | `./var/blobs` | Root directory where blob files are persisted. |
| `temp_prefix` | `blobtmp` | Prefix used for temporary files created during atomic writes. |
| `fsync_writes` | `true` | When `true`, fsync temp files before atomic replace. |
| `default_extension` | `blob` | Default extension used when OAS put requests omit extension. |

### `resources.adapter.litellm`
LiteLLM adapter connection defaults.

| Key | Default | Description |
|---|---|---|
| `base_url` | `http://litellm:4000` | Base URL for LiteLLM gateway HTTP endpoints. |
| `api_key` | `""` | Optional API token sent as `Authorization: Bearer <token>`. |
| `timeout_seconds` | `30.0` | Per-request HTTP timeout. Must be > 0. |
| `max_retries` | `2` | Number of retries for dependency-style failures (network/5xx). Must be >= 0. |

### `resources.substrate.obsidian`
Obsidian Local REST API substrate defaults.

| Key | Default | Description |
|---|---|---|
| `base_url` | `http://host.docker.internal:27123` | Base URL for the Obsidian Local REST API instance. |
| `api_key` | `""` | Optional API token sent as `Authorization: Bearer <token>`. |
| `timeout_seconds` | `10.0` | Per-request HTTP timeout in seconds. Must be > 0. |
| `max_retries` | `2` | Number of retries for dependency-style failures (network/5xx/429). Must be >= 0. |

### `resources.adapter.signal`
Signal runtime adapter defaults.

| Key | Default | Description |
|---|---|---|
| `base_url` | `http://signal-api:8080` | Base URL for Signal runtime receive/health endpoints. |
| `receive_e164` | `+13333333333` | E.164 identity subscribed for inbound messages via `/v1/receive/{number}`. |
| `health_timeout_seconds` | `0.5` | Per-request timeout in seconds for Signal health probes. Must be > 0. |
| `receive_connect_timeout_seconds` | `10.0` | WebSocket connect timeout in seconds for `/v1/receive/{number}`. Must be > 0. |
| `receive_heartbeat_seconds` | `30.0` | WebSocket heartbeat interval in seconds for `/v1/receive/{number}`. Must be > `receive_connect_timeout_seconds`. |
| `send_timeout_seconds` | `30.0` | Per-request HTTP timeout in seconds for outbound `/v2/send` calls. Must be > 0. |
| `callback_timeout_seconds` | `10.0` | Per-request HTTP timeout in seconds for webhook callback POSTs into Switchboard. Must be > 0. |
| `max_retries` | `2` | Number of retries for dependency-style failures (network/5xx). Must be >= 0. |
| `failure_backoff_initial_seconds` | `1.0` | Initial delay after receive/callback failure before retry. Must be > 0. |
| `failure_backoff_max_seconds` | `30.0` | Maximum capped delay for failure backoff. Must be > 0. |
| `failure_backoff_multiplier` | `2.0` | Exponential multiplier applied to each consecutive failure delay. Must be > 1.0. |
| `failure_backoff_jitter_ratio` | `0.2` | Symmetric random jitter ratio applied to failure delays. Must be in `[0,1)`. |

### `core.service.embedding_authority`
Embedding Authority Service runtime settings.

| Key | Default | Description |
|---|---|---|
| `max_list_limit` | `500` | Maximum number of results returned by list operations. Must be > 0. |

### `core.service.cache_authority`
Cache Authority Service runtime settings.

| Key | Default | Description |
|---|---|---|
| `key_prefix` | `brain` | Non-empty prefix used for Redis key and queue namespacing. |
| `default_ttl_seconds` | `300` | Default TTL applied when `set_value` is called without explicit TTL. Must be > 0. |
| `allow_non_expiring_keys` | `true` | When `true`, `ttl_seconds=0` is allowed and maps to non-expiring keys. |

### `core.service.memory_authority`
Memory Authority Service runtime settings.

| Key | Default | Description |
|---|---|---|
| `dialogue_recent_turns` | `10` | Number of recent dialogue turns included verbatim in assembled context. Must be > 0. |
| `dialogue_older_turns` | `20` | Maximum number of older turns considered for summarized dialogue context. Must be >= 0. |
| `focus_token_budget` | `512` | Hard token ceiling for session focus content. Must be > 0. |

### `core.service.object_authority`
Object Authority Service runtime settings.

| Key | Default | Description |
|---|---|---|
| `digest_algorithm` | `sha256` | Digest algorithm used for object key generation. Currently only `sha256` is supported. |
| `digest_version` | `b1` | Object key version prefix used in canonical object keys. |
| `max_blob_size_bytes` | `52428800` | Maximum accepted blob payload size in bytes for `put_object`. Must be > 0. |

### `core.service.vault_authority`
Vault Authority Service runtime settings.

| Key | Default | Description |
|---|---|---|
| `max_list_limit` | `500` | Maximum list operation limit accepted by VAS. Must be > 0. |
| `max_search_limit` | `200` | Maximum lexical search result limit accepted by VAS. Must be > 0. |

### `core.service.language_model`
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

### `core.service.switchboard`
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

### `core.service.capability_engine`
Capability Engine Service runtime settings.

| Key | Default | Description |
|---|---|---|
| `discovery_root` | `capabilities` | Root directory scanned recursively for capability packages. Intermediate directories are organizational only; package directory names must still match `capability_id`. |
| `default_max_autonomy` | `0` | Default engine autonomy ceiling used when evaluating capability execution. Must be >= 0. |

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
