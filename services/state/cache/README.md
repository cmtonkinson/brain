# Cache Service
State *Service* that owns scoped cache and queue behavior, gates Valkey access, and exposes envelope-based cache/queue APIs to other components.

------------------------------------------------------------------------
## What This Component Is
`services/state/cache/` is the authoritative Tier 2 *Service* for
cache and queue operations in Brain.

Core module roles:
* `component.py`: `ServiceManifest` registration (`service_cache`)
* `service.py`: authoritative in-process public API contract
* `implementation.py`: concrete service behavior (`DefaultCacheService`)
* `config.py`: service-level runtime behavior settings
* `domain.py`: Pydantic payload contracts for Cache responses
* `validation.py`: Pydantic ingress request-validation models

------------------------------------------------------------------------
## Boundary and Ownership
Cache is a State-System *Service* (`tier=2`, `plane="state"`) and declares
ownership of `substrate_valkey` in
`services/state/cache/component.py`.

Ownership boundaries:
* Cache owns scoped key/queue naming semantics and TTL policy.
* Cache owns request validation and error mapping at service boundaries.
* Valkey substrate is infrastructure dependency only; business behavior remains
  in Cache.

------------------------------------------------------------------------
## Interactions
Primary interactions with the rest of Brain:
* callers use `CacheService` (`service.py`) as the canonical in-process
  API surface.
* Cache validates requests and metadata, builds scoped keys/queues, and delegates
  Valkey operations to `ValkeySubstrate`.
* Cache returns typed envelopes with payloads from `domain.py` and shared
  structured errors.
* Cache health checks use substrate `ping` and publish service/substrate readiness
  status.

------------------------------------------------------------------------
## Operational Flow (High Level)
1. Cache is constructed from typed settings with `from_settings(...)` or by
   dependency injection.
2. Requests enter through `service.py` methods with `EnvelopeMeta`.
3. Metadata and request payloads are validated with models in
   `validation.py`.
4. Cache applies component-scoped key/queue naming and TTL resolution rules.
5. Cache delegates data operations to Valkey substrate methods.
6. Cache returns typed envelopes with payload or structured errors.

------------------------------------------------------------------------
## Failure Modes and Error Semantics
* metadata/request validation failures return validation-category errors.
* Valkey runtime failures are mapped to dependency-category errors.
* malformed stored JSON payloads are surfaced as internal-category errors.
* queue read operations return success with `None` payload when empty.
* health returns service readiness plus substrate readiness/details.

------------------------------------------------------------------------
## Configuration Surface
Cache service settings are sourced from `components.service.cache`:
* `key_prefix`
* `default_ttl_seconds`
* `allow_non_expiring_keys`

Cache consumes Valkey substrate settings from `components.substrate.valkey` via
`resolve_valkey_settings(...)`.

See `docs/configuration.md` for canonical key definitions and environment
override rules.

------------------------------------------------------------------------
## Testing and Validation
Component tests:
* `services/state/cache/tests/test_cache_service.py`

Related substrate coverage:
* `resources/substrates/valkey/tests/test_valkey_config.py`
* `resources/substrates/valkey/tests/test_valkey_substrate.py`

Project-wide validation command:
```bash
make test
```

------------------------------------------------------------------------
## Contributor Notes
* Keep `service.py` as the authoritative Cache API surface for callers.
* Keep request and payload contracts in Pydantic models with strict validation.
* Keep Valkey dependency details inside Cache implementation and substrate modules.
* Preserve component-scoped namespacing semantics (`component_id` + key/queue).
* If API or config shape changes, update this README and
  `docs/configuration.md` in the same change.


------------------------------------------------------------------------
_End of Cache Service README_
