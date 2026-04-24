# Object Service
State _Service_ that owns content-addressed object metadata authority and
durable blob lifecycle semantics on top of Postgres metadata and a SeaweedFS
substrate.

------------------------------------------------------------------------
## What This Component Is
`services/state/object/` is the authoritative Tier 2 _Service_ for
blob object operations in Brain.

Core module roles:
- `component.py`: `ServiceManifest` registration (`service_object`)
- `service.py`: authoritative in-process public API contract
- `implementation.py`: default Object behavior (`DefaultObjectService`)
- `domain.py`: strict payload contracts for object records/results
- `validation.py`: request-validation and object-key semantics
- `data/`: Postgres runtime, schema, and repository implementation
- `migrations/`: Alembic environment and schema migrations

------------------------------------------------------------------------
## Boundary and Ownership
Object is a State-System _Service_ (`tier=2`, `plane="state"`) and declares
ownership of `substrate_seaweedfs` in
`services/state/object/component.py`.

Ownership boundaries:
- Object owns object-key semantics (`b1:sha256:<digest>`), request validation, and
  error mapping.
- Object owns authoritative metadata in Postgres.
- SeaweedFS substrate owns provider key derivation and S3-compatible blob IO.

------------------------------------------------------------------------
## Interactions
Primary interactions:
- Callers use `ObjectService` (`service.py`) as the canonical
  in-process API.
- Object validates requests and metadata, computes seeded digest/object key, and
  persists metadata via repository operations.
- Object persists blob bytes through `SeaweedFSBlobSubstrate`.
- Object maps dependency and not-found behavior into envelope errors.

------------------------------------------------------------------------
## Operational Flow (High Level)
1. `put_object` validates request, computes seeded digest, upserts metadata row,
   and writes blob bytes idempotently.
2. `get_object` resolves object by key from metadata and returns object + blob
   content.
3. `stat_object` resolves object metadata only.
4. `delete_object` deletes provider object best-effort, deletes metadata row,
   and returns idempotent success.

------------------------------------------------------------------------
## Failure Modes and Error Semantics
- Invalid metadata/request fields return validation-category errors.
- Missing objects return not-found-category errors for `get`/`stat`.
- `delete_object` is idempotent and returns `True` even when object is absent.
- Postgres and SeaweedFS runtime failures map to dependency-category errors.

------------------------------------------------------------------------
## Configuration Surface
Object service settings are sourced from `components.service.object`:
- `digest_algorithm`
- `digest_version`
- `max_blob_size_bytes`

Object consumes SeaweedFS substrate settings from
`components.substrate.seaweedfs`.

------------------------------------------------------------------------
## Testing and Validation
Component tests:
- `services/state/object/tests/test_object_service.py`
- `services/state/object/tests/test_object_repository.py`
- `services/state/object/tests/test_object_api.py`

Project-wide validation command:
```bash
make test
```


------------------------------------------------------------------------
_End of Object Service README_
