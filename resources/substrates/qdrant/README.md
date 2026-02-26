# Qdrant Substrate
Vector-search _Substrate_ _Resource_ used by the Embedding Authority _Service_ for derived semantic index storage and retrieval.

------------------------------------------------------------------------
## What This Component Is
`resources/substrates/qdrant/` provides the concrete Qdrant integration used by
Brain:
- manifest registration (`component.py`)
- immutable runtime config model (`config.py`)
- substrate protocol plus typed point/search DTOs (`substrate.py`)
- qdrant-client construction (`client.py`)
- concrete substrate implementation (`qdrant_substrate.py`)

The package exports `QdrantConfig`, `QdrantSubstrate`, `RetrievedPoint`,
`SearchPoint`, `QdrantClientSubstrate`, and `MANIFEST`.

------------------------------------------------------------------------
## Boundary and Ownership
This _Resource_ is owned by `service_embedding_authority` via
`owner_service_id` in `resources/substrates/qdrant/component.py`.

It is a Layer 0 substrate focused on vector index operations only. It does not
own embedding domain invariants, spec lifecycle, or request validation; those
remain in the Embedding Authority _Service_.

------------------------------------------------------------------------
## Interactions
Primary system interactions:
- EAS constructs per-spec substrates via `QdrantEmbeddingBackend` in
  `services/state/embedding_authority/qdrant_backend.py`.
- `QdrantEmbeddingBackend` builds `QdrantConfig` and instantiates
  `QdrantClientSubstrate` per `spec_id` (one collection per embedding spec).
- EAS uses substrate calls to:
  - ensure collections exist and match dimensions
  - upsert/delete chunk vectors
  - run filtered semantic search (`source_id` filter when provided)
- substrate operations are instrumented via
  `packages.brain_shared.logging.public_api_instrumented`.

------------------------------------------------------------------------
## Operational Flow (High Level)
1. EAS resolves Qdrant substrate settings (`url`, `request_timeout_seconds`,
   `distance_metric`) from `components.substrate.qdrant`.
2. EAS creates `QdrantConfig` for a spec collection and instantiates
   `QdrantClientSubstrate`.
3. `QdrantClientSubstrate` creates a `QdrantClient` with URL and timeout.
4. On first upsert, `_ensure_collection(...)` creates the collection with the
   configured distance metric and vector dimension.
5. Upsert/retrieve/delete/search execute against the configured collection.
6. Search returns normalized `SearchPoint` results with score and payload.

------------------------------------------------------------------------
## Failure Modes and Error Semantics
- invalid substrate configuration fails fast through `QdrantConfig` model
  validation (`extra="forbid"`, required fields, supported distance metric).
- collection-missing reads/searches are non-throwing and return `None`/empty
  results, which keeps derived-index behavior explicit and predictable.
- delete against a missing collection returns `False` and does not issue a
  delete request.
- collection dimension mismatch is raised by EAS backend as a `ValueError` when
  an existing collection does not match the required embedding dimensions.
- transport/runtime failures from qdrant-client bubble to EAS, which maps them
  to service-level structured dependency errors.

------------------------------------------------------------------------
## Configuration Surface
Substrate-level runtime fields (from `QdrantConfig`):
- `url`
- `timeout_seconds`
- `collection_name`
- `distance_metric`

Substrate component settings (`QdrantSettings`) are sourced from:
- `components.substrate.qdrant.url`
- `components.substrate.qdrant.request_timeout_seconds`
- `components.substrate.qdrant.distance_metric`

See `docs/configuration.md` for canonical key definitions and overrides.

------------------------------------------------------------------------
## Testing and Validation
Component tests:
- `resources/substrates/qdrant/tests/test_config.py`
- `resources/substrates/qdrant/tests/test_qdrant_substrate.py`

Related integration/behavior coverage:
- `services/state/embedding_authority/tests/test_qdrant_backend.py`

Project-wide validation command:
```bash
make test
```

------------------------------------------------------------------------
## Contributor Notes
- Keep this component focused on direct Qdrant substrate operations.
- Keep DTO/config models in Pydantic and aligned with contract rules in
  `docs/conventions.md`.
- Do not add service-domain policy or orchestration logic here.
- Maintain operation instrumentation on public substrate methods.
- If substrate API shape changes, update this README and EAS backend callsites
  together.

------------------------------------------------------------------------
_End of Qdrant Substrate README_
