# Embedding Authority Service
State _Service_ that owns embedding specs, sources, chunks, and embedding materialization state, and coordinates derived semantic indexing through the Qdrant substrate.

------------------------------------------------------------------------
## What This Component Is
`services/state/embedding_authority/` is the authoritative Layer 1 _Service_
for embedding-related state and lookup behavior.

Core module roles:
- `component.py`: `ServiceManifest` registration (`service_embedding_authority`)
- `service.py`: authoritative in-process public API contract
- `implementation.py`: concrete service behavior (`DefaultEmbeddingAuthorityService`)
- `api.py`: gRPC adapter for Layer 2 callers
- `domain.py`: Pydantic domain contracts for service payloads
- `validation.py`: Pydantic request-validation models at ingress boundaries
- `data/`: Postgres runtime, schema, and repository implementation
- `qdrant_backend.py`: derived-index orchestration over the Qdrant substrate

------------------------------------------------------------------------
## Boundary and Ownership
EAS is a State-System _Service_ (`layer=1`, `system="state"`) and declares
ownership of `substrate_qdrant` in `services/state/embedding_authority/component.py`.

Authority boundaries:
- authoritative state is in Postgres under the EAS-owned schema
  (`service_embedding_authority`)
- derived vector index data is stored in Qdrant (one collection per `spec_id`)
- EAS owns spec/source/chunk/embedding invariants and request semantics
- Qdrant substrate remains an infrastructure dependency; business rules stay in
  EAS

------------------------------------------------------------------------
## Interactions
Primary interactions with the rest of Brain:
- in-process callers use `EmbeddingAuthorityService` (`service.py`)
- Layer 2 callers use gRPC via `GrpcEmbeddingAuthorityService` (`api.py`)
- authoritative persistence flows through `PostgresEmbeddingRepository`
  (`data/repository.py`)
- schema-scoped DB sessions are provided by
  `ServiceSchemaSessionProvider` via `EmbeddingPostgresRuntime`
  (`data/runtime.py`)
- derived index operations flow through `QdrantEmbeddingBackend`
  (`qdrant_backend.py`), which composes `QdrantClientSubstrate`
- envelope metadata and typed errors are propagated through all public calls

------------------------------------------------------------------------
## Operational Flow (High Level)
1. EAS is constructed from typed settings (`from_settings(...)`) or with
   injected repository/index dependencies.
2. Requests enter through `service.py` methods (or `api.py` gRPC transport
   mappings) with envelope metadata.
3. EAS validates metadata and request payloads with Pydantic models from
   `validation.py`.
4. Authoritative records are read/written in Postgres via
   `PostgresEmbeddingRepository`.
5. For vector writes/searches, EAS resolves effective spec and coordinates
   Qdrant operations through `QdrantEmbeddingBackend`.
6. Responses return as typed envelopes with payload and/or structured errors.

Key behavior patterns:
- spec identity is canonicalized and hash-based for idempotent upsert
- active spec can be persisted and used when `spec_id` is omitted
- vector dimension checks are enforced against resolved spec dimensions
- delete operations perform best-effort derived-index cleanup after authoritative
  deletes

------------------------------------------------------------------------
## Failure Modes and Error Semantics
- request/metadata validation failures return typed validation errors.
- not-found cases (`spec`, `source`, `chunk`, `embedding`, active spec) return
  typed not-found errors.
- Postgres failures are normalized through
  `resources/substrates/postgres/errors.py`.
- Qdrant dependency failures are surfaced as typed dependency errors.
- in gRPC transport (`api.py`), dependency/internal categories are mapped to
  transport aborts (`UNAVAILABLE` / `INTERNAL`), while domain errors remain in
  response envelopes.

------------------------------------------------------------------------
## Configuration Surface
EAS service-local settings are sourced from
`components.service.embedding_authority`:
- `max_list_limit`

Qdrant substrate settings are sourced from `components.substrate.qdrant`:
- `url`
- `request_timeout_seconds`
- `distance_metric`

Postgres substrate settings are sourced from `components.substrate.postgres` by
`EmbeddingPostgresRuntime`.

See `docs/configuration.md` for canonical key definitions and override rules.

------------------------------------------------------------------------
## Testing and Validation
Component tests:
- `services/state/embedding_authority/tests/test_service.py`
- `services/state/embedding_authority/tests/test_api.py`
- `services/state/embedding_authority/tests/test_repository.py`
- `services/state/embedding_authority/tests/test_qdrant_backend.py`

Project-wide validation command:
```bash
make test
```

------------------------------------------------------------------------
## Contributor Notes
- Keep `service.py` as the authoritative API surface; do not bypass it with
  cross-service internal imports.
- Keep request/domain contracts in Pydantic models and enforce validation at
  ingress.
- Preserve the authoritative/derived split:
  - Postgres is authoritative
  - Qdrant is derived index storage
- Keep schema isolation strict via `ServiceSchemaSessionProvider`.
- Keep transport mapping concerns in `api.py` and business logic in
  `implementation.py`.

------------------------------------------------------------------------
_End of Embedding Authority Service README_
