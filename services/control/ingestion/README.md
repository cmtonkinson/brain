# Ingestion Service
Control _Service_ that owns content-ingestion attempts, stage execution state, artifact lineage, provenance, anchor-note linkage, and derived indexing handoff records.

------------------------------------------------------------------------
## What This Component Is
`services/control/ingestion/` is the authoritative Layer 1 _Service_ for deterministic content ingestion in Brain's Control System.

Core module roles:
- `component.py`: `ServiceManifest` registration (`service_ingestion`)
- `service.py`: authoritative in-process public API contract (`IngestionService`)
- `implementation.py`: concrete service behavior (`DefaultIngestionService`)
- `config.py`: service-level runtime settings (`IngestionServiceSettings`)
- `domain.py`: Pydantic payload contracts for ingestions, stage outcomes, provenance, anchors, and indexing runs
- `interfaces.py`: persistence contract plus extractor/normalizer plugin contracts
- `api.py`: published HTTP subset for submission, status, results, retry, replay, and health
- `data/`: Postgres runtime, schema, and repository
- `migrations/`: Alembic environment scoped to `service_ingestion`

------------------------------------------------------------------------
## Boundary and Ownership
Ingestion Service is a Control-System _Service_ (`layer=1`, `system="control"`). It owns the `service_ingestion` Postgres schema exclusively.

Authority boundaries:
- Ingestion attempts, stage runs, per-artifact outcomes, extraction/normalization metadata, provenance records, anchor links, and indexing-run records are owned only by this service.
- Blob persistence routes through `ObjectAuthorityService` public APIs only.
- Vault anchor writes route through `VaultAuthorityService` public APIs only.
- Stage and indexing orchestration routes through `JobService` and Capability Engine capability invocation.
- Derived indexing uses `UtilityService`, `LanguageModelService`, and `EmbeddingAuthorityService` public APIs only.

------------------------------------------------------------------------
## Implemented v1 Behavior
- Submission accepts exactly one inline payload or existing object key and requires timezone-aware capture time.
- Store runs inline so raw payload bytes are still available, then follow-up stage advancement runs as a paused one-shot job invoked with `run_job_now()`.
- Built-in text extraction/normalization supports UTF-8 `text/*`, Markdown MIME aliases, and `application/json`.
- Unsupported artifact types fail extraction explicitly; they do not silently complete the pipeline.
- Anchor stage writes human-readable vault notes and records normalized-object to vault-path linkage.
- Successful anchor runs enqueue `ingestion-index-anchored` as a paused one-shot job for derived indexing.
- Retry and replay preserve prior stage history and only rerun stages whose latest run did not succeed unless explicitly forced.

------------------------------------------------------------------------
## Testing and Validation
Component tests live in `services/control/ingestion/tests/`.

Project-wide validation command:
```bash
make test integration
```


------------------------------------------------------------------------
_End of Ingestion Service README_
