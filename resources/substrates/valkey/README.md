# Valkey Substrate
Valkey-backed _Substrate_ _Resource_ used by the Cache _Service_ for scoped cache storage, queue operations, and substrate liveness checks.

------------------------------------------------------------------------
## What This Component Is
`resources/substrates/valkey/` provides the Tier 1 Valkey integration for Brain:
- manifest registration (`component.py`)
- strict runtime settings and resolution (`config.py`)
- transport-agnostic substrate protocol (`substrate.py`)
- valkey-py client construction (`client.py`)
- concrete substrate implementation (`valkey_substrate.py`)

The package exports `ValkeySettings`, `ValkeySubstrate`,
`ValkeyClientSubstrate`, and `MANIFEST`.

------------------------------------------------------------------------
## Boundary and Ownership
This _Resource_ is owned by `service_cache` via
`owner_service_id` in `resources/substrates/valkey/component.py`.

It is infrastructure-only and intentionally does not implement cache policy,
TTL semantics, request validation, or envelope behavior; those concerns remain
in the owning _Service_.

------------------------------------------------------------------------
## Interactions
Primary interactions with the rest of Brain:
- Cache resolves component settings via `resolve_valkey_settings(...)`.
- Cache constructs the substrate with `ValkeyClientSubstrate(...)`.
- Cache performs cache and queue operations through the `ValkeySubstrate`
  protocol (`set_value`, `get_value`, `delete_value`, `push_queue`,
  `pop_queue`, `peek_queue`, `ping`).
- Valkey failures are surfaced to Cache for mapping into service-level structured
  dependency errors.

------------------------------------------------------------------------
## Operational Flow (High Level)
1. Runtime settings are loaded from `components.substrate.valkey`.
2. `ValkeySettings` resolves explicit URL mode or split-field URL construction.
3. `create_valkey_client(...)` builds a valkey-py client from resolved settings.
4. `ValkeyClientSubstrate` performs direct Valkey key/value and list operations.
5. Cache composes these operations into service-level behavior and envelopes.

------------------------------------------------------------------------
## Failure Modes and Error Semantics
- invalid substrate settings fail fast through Pydantic model validation.
- missing `password_env` references fail at settings resolution when split-field
  mode is used.
- runtime Valkey failures are not swallowed in this component; they propagate to
  Cache for consistent dependency error mapping.
- `pop_queue`/`peek_queue` return `None` for empty queues.
- `delete_value` returns a boolean indicating whether a key was removed.

------------------------------------------------------------------------
## Configuration Surface
Settings are sourced from `components.substrate.valkey`:
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
- `health_timeout_seconds`
- `max_connections`

See `docs/configuration.md` for canonical key definitions and environment
override rules.

------------------------------------------------------------------------
## Testing and Validation
Component tests:
- `resources/substrates/valkey/tests/test_valkey_config.py`
- `resources/substrates/valkey/tests/test_valkey_substrate.py`

Project-wide validation command:
```bash
make test
```

------------------------------------------------------------------------
## Contributor Notes
- Keep this component focused on direct Valkey substrate operations.
- Keep all domain-level policy in Cache.
- Keep the substrate protocol and implementation signatures aligned so Cache can
  depend only on the protocol contract.
- If substrate API shape changes, update this README and Cache callsites
  together.


------------------------------------------------------------------------
_End of Valkey Substrate README_
