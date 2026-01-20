<!--
Docblock:
- File: docs/scheduler-adapter-config-boundary.md
- Purpose: Define the Celery + Redis adapter alignment and configuration boundary for scheduler swaps.
- Scope: Epic 02 scheduler selection and decoupling; Milestone 01 scheduling foundations.
-->
# Scheduler Adapter and Config Boundary

## Purpose
Document how the provider-agnostic adapter boundary maps to Celery + Redis integration points while
making configuration boundaries explicit for future scheduler swaps. This note aligns with the
adapter contracts in `docs/scheduling-architecture-note.md` and keeps provider-specific details
isolated.

## Adapter Boundary Alignment (Celery + Redis)
The adapter interface defined in `docs/scheduling-architecture-note.md` is implemented as a thin
translation layer around Celery Beat + worker + Redis, without leaking Celery semantics into Brain
logic.

### Provider-Agnostic Adapter Calls
- `register_schedule(schedule_id, schedule_payload)`
- `update_schedule(schedule_id, schedule_payload)`
- `pause_schedule(schedule_id)`
- `resume_schedule(schedule_id)`
- `delete_schedule(schedule_id)`
- `trigger_callback(schedule_id, scheduled_for)`

### Celery + Redis Mapping (Implementation Detail)
- **register/update**: translate Brain schedule definition into Celery Beat entries (ETA/interval/
  crontab) and enqueue callbacks with `schedule_id` + `scheduled_for` payload.
- **pause/resume**: enable/disable Beat entries; Brain remains the source of truth for state.
- **delete**: remove Beat entry and ignore any orphan callbacks by validating in the dispatcher.
- **trigger_callback**: Celery task executes the provider callback contract and calls the Brain
  dispatcher endpoint with the provider payload.

### Provider-Specific Assumptions (Isolated)
- Celery Beat is the schedule trigger engine; it may be a singleton unless HA is configured.
- Redis is used as broker (and optionally result backend) for Celery tasks.
- Celery task IDs, queue names, and ETA semantics are internal to the adapter and must not appear
  in Brain schedule/execution records or public contracts.
- Conditional schedules are not native to Celery and remain Brain-owned; the adapter only handles
  the evaluation cadence schedule that triggers predicate evaluation.

## Configuration Boundary
Configuration follows Brain's standard patterns (YAML config + env overrides). The adapter reads
provider-agnostic settings from a scheduler config block and provider-specific settings from a
nested provider block. No schema or API contracts change when swapping providers.

### Provider-Agnostic Settings (Stable Across Providers)
These settings are used by Brain scheduling services regardless of provider:
- `scheduler.provider` (string, required; e.g., `celery`)
- `scheduler.timezone` (IANA timezone for schedule evaluation)
- `scheduler.callback_url` (dispatcher callback base URL)
- `scheduler.callback_timeout_seconds` (timeout for provider callback delivery)
- `scheduler.default_max_attempts` (execution retry ceiling)
- `scheduler.default_backoff_strategy` (`fixed`, `exponential`, `none`)
- `scheduler.allowed_schedule_types` (list; must include `one_time`, `interval`, `calendar_rule`,
  `conditional`)

### Provider-Specific Settings (Isolated Per Provider)
These settings are scoped to the provider block and must not be referenced outside the adapter:
- `scheduler.providers.celery.broker_url`
- `scheduler.providers.celery.result_backend`
- `scheduler.providers.celery.queue_name`
- `scheduler.providers.celery.beat_schedule_refresh_seconds`
- `scheduler.providers.celery.task_serializer`
- `scheduler.providers.celery.accept_content`
- `scheduler.providers.celery.worker_prefetch_multiplier`

## Migration Considerations
Swapping providers must not require changes to:
- Domain models (`TaskIntent`, `Schedule`, `Execution`).
- Schedule management API contract.
- Execution invocation contract.
- Audit logging fields or actor context envelopes.

Provider swap should only require:
- Implementing the adapter for the new provider.
- Updating `scheduler.provider` and provider-specific config block.
- Updating deployment/service definitions for the provider runtime.

## Swap Checklist
**Must change**
- Adapter implementation module.
- Provider runtime services (containers, workers, schedulers).
- Provider config block values (broker, queue, connection details).

**Must not change**
- Brain schedule/execution schemas and invariants.
- Contracts in `docs/schedule-management-api-contract.md` and
  `docs/execution-invocation-contract.md`.
- Dispatcher validation logic and actor context enforcement.
- Audit log field definitions.

## Validation Notes
- Adapter boundary should be reviewed against `docs/scheduling-architecture-note.md` and the
  scheduler decision record to ensure no Celery semantics leak into Brain-owned logic.
- Provider-specific settings must remain isolated in configuration and must not be referenced in
  first-party services outside the adapter.

## References
- `docs/prd-scheduled-timed-tasks.md`
- `docs/scheduling-architecture-note.md`
- `docs/schedule-management-api-contract.md`
- `docs/execution-invocation-contract.md`
- `docs/scheduler-decision-record.md`
