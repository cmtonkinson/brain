# Redis Substrate
Redis-backed _Substrate_ _Resource_ used by the Cache Authority _Service_ for scoped cache storage, queue operations, and substrate liveness checks.

------------------------------------------------------------------------
## What This Component Is
`resources/substrates/redis/` provides the Layer 0 Redis integration for Brain:
- manifest registration (`component.py`)
- strict runtime settings and resolution (`config.py`)
- transport-agnostic substrate protocol (`substrate.py`)
- redis-py client construction (`client.py`)
- concrete substrate implementation (`redis_substrate.py`)

The package exports `RedisSettings`, `RedisSubstrate`,
`RedisClientSubstrate`, and `MANIFEST`.

------------------------------------------------------------------------
## Boundary and Ownership
This _Resource_ is owned by `service_cache_authority` via
`owner_service_id` in `resources/substrates/redis/component.py`.

It is infrastructure-only and intentionally does not implement cache policy,
TTL semantics, request validation, or envelope behavior; those concerns remain
in the owning _Service_.

------------------------------------------------------------------------
## Interactions
Primary interactions with the rest of Brain:
- CAS resolves component settings via `resolve_redis_settings(...)`.
- CAS constructs the substrate with `RedisClientSubstrate(...)`.
- CAS performs cache and queue operations through the `RedisSubstrate`
  protocol (`set_value`, `get_value`, `delete_value`, `push_queue`,
  `pop_queue`, `peek_queue`, `ping`).
- Redis failures are surfaced to CAS for mapping into service-level structured
  dependency errors.

------------------------------------------------------------------------
## Operational Flow (High Level)
1. Runtime settings are loaded from `components.substrate.redis`.
2. `RedisSettings` resolves explicit URL mode or split-field URL construction.
3. `create_redis_client(...)` builds a redis-py client from resolved settings.
4. `RedisClientSubstrate` performs direct Redis key/value and list operations.
5. CAS composes these operations into service-level behavior and envelopes.

------------------------------------------------------------------------
## Failure Modes and Error Semantics
- invalid substrate settings fail fast through Pydantic model validation.
- missing `password_env` references fail at settings resolution when split-field
  mode is used.
- runtime Redis failures are not swallowed in this component; they propagate to
  CAS for consistent dependency error mapping.
- `pop_queue`/`peek_queue` return `None` for empty queues.
- `delete_value` returns a boolean indicating whether a key was removed.

------------------------------------------------------------------------
## Configuration Surface
Settings are sourced from `components.substrate.redis`:
- `url`
- `host`
- `port`
- `db`
- `username`
- `password`
- `password_env`
- `ssl`
- `connect_timeout_seconds`
- `socket_timeout_seconds`
- `max_connections`

See `docs/configuration.md` for canonical key definitions and environment
override rules.

------------------------------------------------------------------------
## Testing and Validation
Component tests:
- `resources/substrates/redis/tests/test_redis_config.py`
- `resources/substrates/redis/tests/test_redis_substrate.py`

Project-wide validation command:
```bash
make test
```

------------------------------------------------------------------------
## Contributor Notes
- Keep this component focused on direct Redis substrate operations.
- Keep all domain-level policy in CAS.
- Keep the substrate protocol and implementation signatures aligned so CAS can
  depend only on the protocol contract.
- If substrate API shape changes, update this README and CAS callsites
  together.

------------------------------------------------------------------------
_End of Redis Substrate README_
