# Job Service
Control _Service_ that owns job intent, schedule state, execution history, and audit
records for all scheduled work in Brain. Exposes envelope-based APIs for job
management, execution tracking, conditional evaluation, retry orchestration, and
health inspection.

------------------------------------------------------------------------
## What This Component Is
`services/control/job/` is the authoritative Layer 1 _Service_ for scheduled work in
Brain's Control System.

Core module roles:
- `component.py`: `ServiceManifest` registration (`service_job`)
- `service.py`: authoritative in-process public API contract (`JobService`)
- `implementation.py`: concrete service behavior (`DefaultJobService`)
- `config.py`: service-level runtime behavior settings (`JobServiceSettings`)
- `domain.py`: Pydantic payload contracts — enums, state machine, schedule
  definitions, execution and audit record types
- `validation.py`: Pydantic ingress request-validation models
- `interfaces.py`: `JobRepository` and `JobProviderAdapter` protocols
- `provider.py`: in-process scheduling provider with polling loop
  (`InProcessJobProvider`)
- `retry.py`: pure retry-policy math (backoff, delay, deadline calculation)
- `timing.py`: pure next-run calculation for all schedule types
- `api.py`: FastAPI route adapters for the published HTTP surface
- `boot.py`: startup readiness hook; declares `substrate_postgres` dependency
- `data/runtime.py`: Postgres session factory and health check
- `data/schema.py`: SQLAlchemy table definitions for the `service_job` schema
- `data/repository.py`: `PostgresJobRepository` — full `JobRepository` implementation
- `migrations/`: Alembic environment scoped to `service_job` schema

------------------------------------------------------------------------
## Boundary and Ownership
Job Service is a Control-System _Service_ (`layer=1`, `system="control"`). It uses
shared Postgres infrastructure; the dependency is declared via `boot.py`
`dependencies = ("substrate_postgres",)`.

Authority boundaries:
- Job Service owns all records in the `service_job` Postgres schema exclusively. No
  other service may query or join against these tables.
- Job Service owns schedule intent, state transitions, execution records, mutation
  audits, execution audits, and predicate evaluation records.
- Provider integration (scheduling backend) is an implementation detail; no provider
  concepts leak into the public API or persisted domain objects.
- All operator-facing notifications must route through Attention Router.
- All capability invocations must route through Capability Engine and Policy Service.
- Conditional predicate resolution must route through allowed service public APIs or
  Capability Engine read-only capabilities — never direct internal imports.

------------------------------------------------------------------------
## Interactions
Primary interactions with the rest of Brain:
- Callers use `JobService` (`service.py`) as the canonical in-process API surface.
- The published HTTP surface (`api.py`) exposes a subset of the API for external
  access: create, get, list, pause, resume, cancel, run-now, list-executions, health.
- `InProcessJobProvider` polls the repository for due jobs and invokes
  `handle_provider_callback` for normal schedules or `evaluate_conditional_job` for
  conditional schedules.
- `evaluate_conditional_job` is invoked on a cadence (scheduled actor context) to
  evaluate conditional schedules through read-only Capability Engine calls.
- `process_retry_due_jobs` is invoked periodically to re-queue executions past their
  `retry_after` deadline.
- `review_job_health` is invoked on a cadence to detect orphaned, consistently
  failing, or long-ignored-paused jobs.

------------------------------------------------------------------------
## Operational Flow (High Level)
1. Job Service is built by `build_job_service(settings, capability_engine_service)`,
   which constructs the `PostgresJobRepository`, `InProcessJobProvider`, and
   `DefaultJobService`.
2. `InProcessJobProvider.start()` launches a daemon polling thread.
3. Commands enter through `JobService` methods with `EnvelopeMeta`; requests are
   validated against `validation.py` models at the ingress boundary.
4. State transitions are validated against `ALLOWED_STATE_TRANSITIONS` before any
   mutation is persisted.
5. Every mutation creates a `JobMutationAudit` record for full traceability.
6. After a mutation, the provider adapter is synchronised (register, update, pause,
   resume, or delete).
7. Provider callbacks arrive via `handle_provider_callback`; the unique constraint on
   `(job_id, trace_id)` enforces idempotency.
8. Scheduled and run-now executions dispatch through Capability Engine using the
   stored job action contract.
9. Execution attempts produce `ExecutionAudit` records at each status transition.
10. Retry candidates are identified by `list_retry_due_executions` and re-queued via
    `process_retry_due_jobs`.
11. All responses are returned as `Envelope[T]` with typed payloads or structured
    errors.

------------------------------------------------------------------------
## Failure Modes and Error Semantics
- Metadata or request validation failures return `validation`-category errors.
- Unknown job or execution IDs return `not_found`-category errors.
- Invalid state transitions (e.g., pausing a canceled job) return
  `conflict`-category errors.
- Postgres runtime failures are mapped to `dependency`-category errors.
- Duplicate provider callbacks (same `job_id` + `trace_id`) return a success
  envelope with `status="duplicate"` — idempotent, not an error.
- Retry limit exhaustion transitions the execution to `failed`; the job's
  `failure_count` is incremented.
- Health returns both service readiness and provider readiness independently.

------------------------------------------------------------------------
## Configuration Surface
Job Service settings are sourced from `components.service.service_job`:
- `default_max_attempts` (default: `3`) — retry limit applied at job creation
- `default_backoff_strategy` (default: `"exponential"`) — `fixed`, `exponential`,
  or `none`
- `default_backoff_base_seconds` (default: `60`) — base delay for backoff math
- `orphan_grace_period_hours` (default: `24`) — age threshold for orphaned-job review
- `consecutive_failure_threshold` (default: `3`) — failure count for review flagging
- `ignored_pause_age_days` (default: `30`) — pause age threshold for review flagging
- `provider_poll_interval_seconds` (default: `15.0`) — provider polling cadence

Job Service consumes Postgres substrate settings from `components.substrate.postgres`
via `resolve_postgres_settings(...)`.

See `docs/configuration.md` for canonical key definitions and environment override
rules.

------------------------------------------------------------------------
## Testing and Validation
Component tests:
- `services/control/job/tests/test_domain.py` — domain model invariants and
  discriminated union round-trips
- `services/control/job/tests/test_validation.py` — request validation models and
  definition validators
- `services/control/job/tests/test_retry.py` — retry math (backoff, delay, deadline)
- `services/control/job/tests/test_timing.py` — next-run calculations for all
  schedule types
- `services/control/job/tests/test_implementation.py` — command/query semantics,
  state machine, callback idempotency, retry dispatch, audit integrity — all using
  in-memory fakes

Project-wide validation command:
```bash
make test integration
```

------------------------------------------------------------------------
## Contributor Notes
- Keep `service.py` as the authoritative Job Service API surface for all callers.
- `create_job` requires an explicit `job_action`; descriptive fields are not treated
  as executable intent.
- `schedule_type` is immutable after creation; `definition` updates are validated
  against the existing type.
- State transitions must always go through `_transition_state`; never write `state`
  directly without a corresponding `JobMutationAudit`.
- Provider operations are synchronous and transactional with service mutations; a
  provider failure rolls back the operation.
- The `(job_id, trace_id)` unique constraint on `executions` is the sole idempotency
  guard for provider callbacks — preserve it.
- Predicate evaluation must stay read-only: deny capabilities that require approval
  or declare side effects, and record every evaluation outcome in
  `predicate_evaluations`.
- If API or config shape changes, update this README and `docs/configuration.md` in
  the same change.

------------------------------------------------------------------------
## Migration Lineage
This service was rebuilt from scratch in the new architecture. The following concepts
from the old `deprecated-brain/src/scheduler/` were preserved (behavior ported,
implementation redesigned):

Reused:
- Timing math — `schedule_timing.py` → `timing.py` (pure next-run calculation for
  one-time, interval, RRULE, and conditional schedules)
- Retry policy math — `retry_policy.py` → `retry.py` (fixed/exponential/none backoff;
  max-attempt guard)
- Schedule validation rules — `schedule_validation.py` → `validation.py` (per-type
  required fields, RRULE frequency whitelist, timezone validation)
- Callback idempotency — `callback_bridge.py` → `(job_id, trace_id)` unique
  constraint + duplicate-detection logic in `handle_provider_callback`
- Execution dispatcher state machine — `execution_dispatcher.py` → `ALLOWED_STATE_TRANSITIONS`
  dict + `_transition_state` helper in `implementation.py`
- Predicate evaluation separated from execution dispatch — `capability_gate.py`
  intent → `evaluate_conditional_job` as a distinct internal orchestration path
- Review/inspection queries for stale jobs — `review_job.py` → `review_job_health`
  + `get_orphaned_jobs`, `get_failing_jobs`, `get_ignored_paused_jobs` in the
  repository
- Audit trail semantics — `data_access.py` audit tables → `job_mutation_audits`,
  `execution_audits`, `predicate_evaluations` tables

Deliberately dropped:
- `agent_invoker.py` — direct agent wiring replaced by service public APIs and
  Capability Engine / Policy Service flows
- `failure_notifications.py` — operator notifications must route through Attention
  Router; no direct signal/adapter imports in job runtime
- `schedule_service_interface.py` command/query dataclass explosion — replaced by
  narrow keyword-argument methods on `JobService`
- Direct imports from ingestion, attention, commitment, or other service internals —
  replaced by public API calls or capability flows
- Old `models.py` monolith SQLAlchemy shape — replaced by isolated per-service schema
  in `data/schema.py`


------------------------------------------------------------------------
_End of Job Service README_
