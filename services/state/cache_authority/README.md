# Cache Authority Service
State _Service_ that owns scoped cache and queue behavior, gates Redis access, and exposes envelope-based cache/queue APIs to other components.

------------------------------------------------------------------------
## What This Component Is
`services/state/cache_authority/` is the authoritative Layer 1 _Service_ for
cache and queue operations in Brain.

Core module roles:
- `component.py`: `ServiceManifest` registration (`service_cache_authority`)
- `service.py`: authoritative in-process public API contract
- `implementation.py`: concrete service behavior (`DefaultCacheAuthorityService`)
- `config.py`: service-level runtime behavior settings
- `domain.py`: Pydantic payload contracts for CAS responses
- `validation.py`: Pydantic ingress request-validation models

------------------------------------------------------------------------
## Boundary and Ownership
CAS is a State-System _Service_ (`layer=1`, `system="state"`) and declares
ownership of `substrate_redis` in
`services/state/cache_authority/component.py`.

Authority boundaries:
- CAS owns scoped key/queue naming semantics and TTL policy.
- CAS owns request validation and error mapping at service boundaries.
- Redis substrate is infrastructure dependency only; business behavior remains
  in CAS.

------------------------------------------------------------------------
## Interactions
Primary interactions with the rest of Brain:
- callers use `CacheAuthorityService` (`service.py`) as the canonical in-process
  API surface.
- CAS validates requests and metadata, builds scoped keys/queues, and delegates
  Redis operations to `RedisSubstrate`.
- CAS returns typed envelopes with payloads from `domain.py` and shared
  structured errors.
- CAS health checks use substrate `ping` and publish service/substrate readiness
  status.

------------------------------------------------------------------------
## Operational Flow (High Level)
1. CAS is constructed from typed settings with `from_settings(...)` or by
   dependency injection.
2. Requests enter through `service.py` methods with `EnvelopeMeta`.
3. Metadata and request payloads are validated with models in
   `validation.py`.
4. CAS applies component-scoped key/queue naming and TTL resolution rules.
5. CAS delegates data operations to Redis substrate methods.
6. CAS returns typed envelopes with payload or structured errors.

------------------------------------------------------------------------
## Failure Modes and Error Semantics
- metadata/request validation failures return validation-category errors.
- Redis runtime failures are mapped to dependency-category errors.
- malformed stored JSON payloads are surfaced as internal-category errors.
- queue read operations return success with `None` payload when empty.
- health returns service readiness plus substrate readiness/details.

------------------------------------------------------------------------
## Configuration Surface
CAS service settings are sourced from `components.service.cache_authority`:
- `key_prefix`
- `default_ttl_seconds`
- `allow_non_expiring_keys`

CAS consumes Redis substrate settings from `components.substrate.redis` via
`resolve_redis_settings(...)`.

See `docs/configuration.md` for canonical key definitions and environment
override rules.

------------------------------------------------------------------------
## Testing and Validation
Component tests:
- `services/state/cache_authority/tests/test_cache_service.py`

Related substrate coverage:
- `resources/substrates/redis/tests/test_redis_config.py`
- `resources/substrates/redis/tests/test_redis_substrate.py`

Project-wide validation command:
```bash
make test
```

------------------------------------------------------------------------
## Contributor Notes
- Keep `service.py` as the authoritative CAS API surface for callers.
- Keep request and payload contracts in Pydantic models with strict validation.
- Keep Redis dependency details inside CAS implementation and substrate modules.
- Preserve component-scoped namespacing semantics (`component_id` + key/queue).
- If API or config shape changes, update this README and
  `docs/configuration.md` in the same change.

------------------------------------------------------------------------
_End of Cache Authority Service README_
