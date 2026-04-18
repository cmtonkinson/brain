# Commitment Service
Control _Service_ that owns commitment lifecycle, progress, transition audit, review state, and commitment-to-job linkage for loop closure in Brain.

------------------------------------------------------------------------
## What This Component Is
`services/control/commitment/` is the authoritative Layer 1 _Service_ for commitment tracking in Brain's Control System.

Core module roles:
- `component.py`: `ServiceManifest` registration (`service_commitment`)
- `service.py`: authoritative in-process public API contract (`CommitmentService`)
- `implementation.py`: concrete service behavior (`DefaultCommitmentService`)
- `config.py`: service-level runtime settings (`CommitmentServiceSettings`)
- `domain.py`: Pydantic payload contracts for commitments, proposals, reviews, and job links
- `validation.py`: ingress request-validation models
- `interfaces.py`: persistence contract for commitment-owned state
- `api.py`: published HTTP subset for direct lifecycle and read operations
- `data/`: Postgres runtime, schema, and repository
- `migrations/`: Alembic environment scoped to `service_commitment`

------------------------------------------------------------------------
## Boundary and Ownership
Commitment Service is a Control-System _Service_ (`layer=1`, `system="control"`). It owns the `service_commitment` Postgres schema exclusively.

Authority boundaries:
- Commitment records, progress rows, transition audit rows, proposal rows, review runs/items, and job links are owned only by this service.
- Follow-up scheduling routes through `JobService` public APIs only.
- Operator-facing review and missed-commitment delivery routes through `AttentionRouterService` only.
- No direct imports from Job, Ingestion, Attention Router, or other service internals are allowed.

------------------------------------------------------------------------
## Implemented v1 Behavior
- Lifecycle states: `OPEN`, `COMPLETED`, `MISSED`, `CANCELED`
- Atomic progress recording with `last_progress_at` update
- Atomic state transitions with audit history
- Creation and transition proposals for low-confidence service-initiated actions
- One active follow-up job link per commitment
- Miss detection via Job -> Capability Engine -> Commitment Service
- Weekly review aggregation and persistence
- Deterministic review delivery through Attention Router
- Explicit typed intake for ingestion-derived commitment candidates

------------------------------------------------------------------------
## Deferred LLM Behavior
See [llm-behavior.md](llm-behavior.md) for the intentionally deferred LMS-backed dedupe, extraction, and review-summary behavior that should be reintroduced later behind stable service boundaries.

------------------------------------------------------------------------
## Testing and Validation
Component tests live in `services/control/commitment/tests/`.

Project-wide validation command:
```bash
make test integration
```


------------------------------------------------------------------------
_End of Commitment Service README_
