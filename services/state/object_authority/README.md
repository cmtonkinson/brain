# Object Authority Service
State _Service_ that owns content-addressed object metadata authority and durable blob lifecycle semantics on top of Postgres metadata and a filesystem adapter.
------------------------------------------------------------------------
## What This Component Is
`services/state/object_authority/` is the authoritative Layer 1 _Service_ for blob object operations in Brain.

Core module roles:
- `component.py`: `ServiceManifest` registration (`service_object_authority`)
- `service.py`: authoritative in-process public API contract
- `implementation.py`: default OAS behavior (`DefaultObjectAuthorityService`)
- `domain.py`: strict payload contracts for object records/results
- `validation.py`: request-validation and object-key semantics
- `data/`: Postgres runtime, schema, and repository implementation
- `api.py`: gRPC transport adapter
- `migrations/`: Alembic environment and schema migrations
------------------------------------------------------------------------
## Boundary and Ownership
OAS is a State-System _Service_ (`layer=1`, `system="state"`) and declares ownership of `adapter_filesystem` in `services/state/object_authority/component.py`.

Authority boundaries:
- OAS owns object-key semantics (`b1:sha256:<digest>`), request validation, and error mapping.
- OAS owns authoritative metadata in Postgres.
- Filesystem adapter owns local disk path resolution and atomic file IO.
------------------------------------------------------------------------
## Interactions
Primary interactions:
- Callers use `ObjectAuthorityService` (`service.py`) as the canonical in-process API.
- OAS validates requests and metadata, computes seeded digest/object key, and persists metadata via repository operations.
- OAS persists blob bytes through `LocalFilesystemBlobAdapter` with safe-write semantics.
- OAS maps dependency and not-found behavior into envelope errors.
------------------------------------------------------------------------
## Operational Flow (High Level)
1. `put_object` validates request, computes seeded digest, upserts metadata row, and writes blob file idempotently.
2. `get_object` resolves object by key from metadata and returns object + blob content.
3. `stat_object` resolves object metadata only.
4. `delete_object` deletes file best-effort, deletes metadata row, and returns idempotent success.
------------------------------------------------------------------------
## Failure Modes and Error Semantics
- Invalid metadata/request fields return validation-category errors.
- Missing objects return not-found-category errors for `get`/`stat`.
- `delete_object` is idempotent and returns `True` even when object is absent.
- Postgres and filesystem runtime failures map to dependency-category errors (transport abort handled by gRPC adapter).
------------------------------------------------------------------------
## Configuration Surface
OAS service settings are sourced from `components.service_object_authority`:
- `digest_algorithm`
- `digest_version`
- `max_blob_size_bytes`

OAS consumes filesystem adapter settings from `components.adapter_filesystem`.
------------------------------------------------------------------------
## Testing and Validation
Component tests:
- `services/state/object_authority/tests/test_object_service.py`
- `services/state/object_authority/tests/test_object_repository.py`
- `services/state/object_authority/tests/test_object_api.py`

Project-wide validation command:
```bash
make test
```
------------------------------------------------------------------------
_End of Object Authority Service README_
