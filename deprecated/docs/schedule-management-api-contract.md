<!--
Docblock:
- File: schedule-management-api-contract.md
- Purpose: Define the internal schedule management service contract for CRUD, run-now, and inspection.
- Scope: Scheduled & Timed Tasks (Epic 01 / Milestone 01).
-->
# Schedule Management API Contract

## Purpose
Define the backend-agnostic, internal service contract for schedule management in Brain. This
contract is provider-agnostic, enforces immutable intent, captures actor context for audit, and
codifies validation for schedule types.

## Scope
- CRUD + pause/resume + run-now commands.
- Inspection queries (read-only).
- Validation rules for schedule types and cadence.
- Actor context requirements and audit capture.
- Inline task intent creation with schedule creation.

## Non-Goals
- HTTP routing or transport concerns.
- Persistence schema or migrations.
- Scheduler provider specifics.

## Core Principles
- Schedules are data, not configuration.
- Task intent is immutable after creation.
- Schedule identity is stable; schedule type is immutable.
- Mutations are audit logged with actor context.
- No JSONB or JSON-encoded string fields.

## Domain References
- `docs/scheduling-domain-model.md`
- `docs/scheduling-architecture-note.md`
- `docs/prd-scheduled-timed-tasks.md`

## Actor Context (Required)
All command methods require a non-empty actor context for authorization and audit.

**ActorContext**
- `actor_type` (e.g., `human`, `scheduled`, `skill`, `system`)
- `actor_id` (nullable identity within actor type)
- `channel` (e.g., `signal`, `web`, `scheduled`)
- `trace_id` (required for correlation)
- `request_id` (optional; external correlation)
- `reason` (optional; free-form reason for mutation)

Validation:
- Missing or empty `actor_type` or `channel` is an error.
- `scheduled` actor_type is not allowed for schedule mutations (reserved for execution).

## Service Interface Module
Single module with command and query paths.

**Module:** `schedule_service_interface`

### Command Methods
- `create_schedule(request: ScheduleCreateRequest, actor: ActorContext) -> ScheduleResult`
- `update_schedule(request: ScheduleUpdateRequest, actor: ActorContext) -> ScheduleResult`
- `pause_schedule(request: SchedulePauseRequest, actor: ActorContext) -> ScheduleResult`
- `resume_schedule(request: ScheduleResumeRequest, actor: ActorContext) -> ScheduleResult`
- `delete_schedule(request: ScheduleDeleteRequest, actor: ActorContext) -> ScheduleDeleteResult`
- `run_now(request: ScheduleRunNowRequest, actor: ActorContext) -> ExecutionRunNowResult`

### Query Methods
- `get_schedule(request: ScheduleGetRequest) -> ScheduleResult`
- `list_schedules(request: ScheduleListRequest) -> ScheduleListResult`
- `get_task_intent(request: TaskIntentGetRequest) -> TaskIntentResult`

## Request/Response Shapes

### ScheduleCreateRequest
- `task_intent` (TaskIntentInput, required)
- `schedule_type` (`one_time`, `interval`, `calendar_rule`, `conditional`)
- `timezone` (IANA timezone string, required)
- `definition` (ScheduleDefinitionInput, required)
- `start_state` (optional; default `active`)
- `idempotency_key` (optional; stable key for safe retries)

### TaskIntentInput
- `summary` (required, non-empty)
- `details` (optional)
- `origin_reference` (optional)

### ScheduleDefinitionInput (by type)
**One-time**
- `run_at` (timestamp, required)

**Interval**
- `interval_count` (int, required, > 0)
- `interval_unit` (`minute`, `hour`, `day`, `week`, `month`)
- `anchor_at` (timestamp, optional)

**Calendar-rule**
- `rrule` (RFC 5545 string, required)
- `calendar_anchor_at` (timestamp, optional)

**Conditional**
- `predicate_subject` (string identifier, required)
- `predicate_operator` (`eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `exists`, `matches`)
- `predicate_value` (string or numeric literal, required unless operator is `exists`)
- `evaluation_interval_count` (int, required, > 0)
- `evaluation_interval_unit` (`minute`, `hour`, `day`, `week`)

### ScheduleUpdateRequest
- `schedule_id` (required)
- `timezone` (optional)
- `definition` (optional; type must match existing schedule_type)
- `state` (optional; limited to allowed transitions)
- `notes` (optional; mutation rationale)

### SchedulePauseRequest
- `schedule_id` (required)
- `reason` (optional)

### ScheduleResumeRequest
- `schedule_id` (required)
- `reason` (optional)

### ScheduleDeleteRequest
- `schedule_id` (required)
- `reason` (optional)

### ScheduleRunNowRequest
- `schedule_id` (required)
- `requested_for` (optional timestamp; defaults to now)
- `reason` (optional)

### ScheduleGetRequest
- `schedule_id` (required)

### ScheduleListRequest
- `state` (optional filter)
- `schedule_type` (optional filter)
- `created_by_actor_type` (optional filter)
- `created_after` (optional timestamp filter)
- `created_before` (optional timestamp filter)
- `limit` (optional; default 100)
- `cursor` (optional; pagination token)

### TaskIntentGetRequest
- `task_intent_id` (required)

### ScheduleResult
- `schedule` (ScheduleView)
- `task_intent` (TaskIntentView)

### ScheduleListResult
- `schedules` (list[ScheduleView])
- `next_cursor` (optional)

### TaskIntentResult
- `task_intent` (TaskIntentView)

### ScheduleDeleteResult
- `schedule_id`
- `state` (final state; `canceled` or `archived`)

### ExecutionRunNowResult (from run-now)
- `schedule_id`
- `scheduled_for`
- `audit_log_id`

## View Shapes

### TaskIntentView
- `id`
- `summary`
- `details`
- `origin_reference`
- `creator_actor_type`
- `creator_actor_id`
- `creator_channel`
- `created_at`
- `superseded_by_intent_id` (nullable)

### ScheduleView
- `id`
- `task_intent_id`
- `schedule_type`
- `state`
- `timezone`
- `definition` (typed fields only; no JSON)
- `next_run_at`
- `last_run_at`
- `last_run_status`
- `failure_count`
- `created_at`
- `created_by_actor_type`
- `created_by_actor_id`
- `updated_at`

### ExecutionView
- `id`
- `schedule_id`
- `task_intent_id`
- `scheduled_for`
- `status`
- `attempt_number`
- `max_attempts`
- `created_at`
- `actor_type` (fixed: `scheduled`)
- `trace_id`

## Validation Rules

### Shared
- `schedule_id` and `task_intent_id` are stable and immutable.
- `schedule_type` is immutable after creation.
- `timezone` must be a valid IANA timezone.
- `state` transitions must follow `docs/scheduling-domain-model.md`.

### One-time
- `run_at` must be in the future at creation time.
- On success, state transitions to `completed` and no further runs occur.

### Interval
- `interval_count` must be > 0.
- `interval_unit` must be in the allowed set.
- `anchor_at` must not be after the computed `next_run_at`.

### Calendar-rule
- `rrule` must parse as RFC 5545.
- `calendar_anchor_at` must not contradict the rule (if provided).

### Conditional
- `predicate_subject` must map to a read-only capability/skill/op.
- `evaluation_interval_count` must be > 0.
- `evaluation_interval_unit` must be in the allowed set.
- `predicate_value` required unless operator is `exists`.

## Mutability Rules
- **Immutable:** schedule id, schedule type, task intent fields, created_by fields.
- **Mutable:** timezone, schedule definition (within type), state, next_run_at, last_run_at,
  last_run_status, failure_count.
- **Task intent updates:** not allowed; new intent must be created and linked via
  `superseded_by_intent_id`.

## Error Semantics
Errors are returned as structured failures with a machine-readable code and message.

**Common error codes**
- `validation_error`
- `not_found`
- `conflict`
- `forbidden`
- `immutable_field`
- `invalid_state_transition`
- `missing_actor_context`
- `invalid_schedule_type`
- `invalid_schedule_definition`
- `invalid_predicate`
- `invalid_calendar_rule`

## Audit Integration
Every command method must emit an audit entry with:
- `event_type` (create/update/pause/resume/delete/run_now)
- `schedule_id`
- `task_intent_id`
- `actor_type`, `actor_id`, `channel`
- `trace_id`, `request_id`
- `occurred_at`
- `diff_summary` (explicit fields changed; no JSON blob)

## Run-Now Semantics
- Allowed for schedules in `active` or `paused` state.
- Not allowed for `canceled`, `archived`, or `completed` schedules.
- Creates a new Execution with `scheduled_for = requested_for || now` and
  `actor_type = scheduled`.
- Execution metadata records `run_reason = manual` and includes the actor context.

## PRD Coverage Checklist
- CRUD + pause/resume/delete/run-now: covered.
- Schedule types: one-time, interval, calendar-rule, conditional.
- Actor context enforcement: required for mutations.
- Audit integration: explicit fields required.
- Immutable intent and stable schedule IDs: enforced.
