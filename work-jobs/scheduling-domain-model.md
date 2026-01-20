<!--
Docblock:
- File: scheduling-domain-model.md
- Purpose: Define domain entities, invariants, and state transitions for scheduled tasks.
- Scope: Scheduled & Timed Tasks (Epic 01 / Milestone 01).
-->
# Scheduling Domain Model

## Purpose
Define the canonical domain model for scheduled tasks (intent, schedule, execution) with explicit
states, transitions, invariants, and audit metadata. This model is scheduler-backend-agnostic and
aligned with Brain doctrine (authority tiers, attention routing, and constrained autonomy).

## Entities

### TaskIntent (Tier 1 — Durable System State)
**Definition:** Human-readable statement of *why* something should happen. Immutable once created.

**Invariants**
- Immutable content; cannot be mutated in place (supersede with a new intent if needed).
- Never promotes memory directly; may only propose memory through the agent.
- Must be attributable and auditable.

**Fields**
- Immutable
  - `id` (stable identifier)
  - `summary` (short human-readable intent)
  - `details` (longer description)
  - `creator_actor_type` (e.g., `human`, `scheduled`, `skill`, `system`)
  - `creator_actor_id` (nullable; identity within actor type)
  - `creator_channel` (e.g., `signal`, `web`, `scheduled`)
  - `created_at`
  - `origin_reference` (link to originating message/note/event)
- Mutable
  - `superseded_by_intent_id` (nullable; points to replacement intent)

### Schedule (Tier 1 — Durable System State)
**Definition:** The *when* of execution, with editable cadence and lifecycle state.

**Invariants**
- Schedule definition is explicit, typed fields (no JSON/JSONB columns).
- Must be linked to a TaskIntent.
- State transitions are constrained to defined lifecycle rules.
- Conditional schedules must define evaluation cadence up front.

**Fields**
- Immutable
  - `id`
  - `task_intent_id`
  - `schedule_type` (`one_time`, `interval`, `calendar_rule`, `conditional`)
  - `created_at`
  - `created_by_actor_type`
  - `created_by_actor_id`
- Mutable
  - `state` (`draft`, `active`, `paused`, `canceled`, `archived`, `completed`)
  - `timezone`
  - `next_run_at`
  - `last_run_at`
  - `last_run_status` (see Execution status)
  - `failure_count`
  - `updated_at`

**Schedule definition fields (mutable; explicit by type)**
- One-time
  - `run_at`
- Interval
  - `interval_count`
  - `interval_unit` (`minute`, `hour`, `day`, `week`, `month`)
  - `anchor_at` (optional start reference)
- Calendar-rule
  - `rrule` (RFC 5545 string; not JSON)
  - `calendar_anchor_at` (optional explicit start)
- Conditional
  - `predicate_subject` (string identifier for capability/skill/op)
  - `predicate_operator` (`eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `exists`, `matches`)
  - `predicate_value` (string or numeric literal)
  - `evaluation_interval_count`
  - `evaluation_interval_unit` (`minute`, `hour`, `day`, `week`)
  - `last_evaluated_at`
  - `last_evaluation_status` (`true`, `false`, `error`, `unknown`)
  - `last_evaluation_error_code` (nullable)

### Execution (Tier 1 — Durable System State; audit-retained)
**Definition:** A single execution attempt derived from a schedule at a specific time.

**Invariants**
- Execution records are append-only and immutable after terminal status.
- Actor context is always `scheduled` with constrained autonomy.
- Execution cannot promote memory directly.

**Fields**
- Immutable
  - `id`
  - `task_intent_id`
  - `schedule_id`
  - `scheduled_for`
  - `created_at`
  - `actor_type` (fixed: `scheduled`)
  - `actor_context` (authorization context envelope identifier)
  - `correlation_id`
- Mutable (until terminal)
  - `status` (`queued`, `running`, `succeeded`, `failed`, `retry_scheduled`, `canceled`)
  - `attempt_number`
  - `max_attempts`
  - `started_at`
  - `finished_at`
  - `failure_count`
  - `retry_backoff_strategy` (`fixed`, `exponential`, `none`)
  - `next_retry_at`
  - `last_error_code`
  - `last_error_message`

## Enums
- ScheduleType: `one_time`, `interval`, `calendar_rule`, `conditional`
- ScheduleState: `draft`, `active`, `paused`, `canceled`, `archived`, `completed`
- ExecutionStatus: `queued`, `running`, `succeeded`, `failed`, `retry_scheduled`, `canceled`
- BackoffStrategy: `fixed`, `exponential`, `none`
- PredicateEvaluationStatus: `true`, `false`, `error`, `unknown`

## Schedule State Transitions

| From | To | Trigger | Notes |
| --- | --- | --- | --- |
| draft | active | create/enable | Requires valid schedule definition |
| active | paused | pause | Preserve next/last run state |
| paused | active | resume | Restore normal cadence |
| active | canceled | cancel | Terminal unless explicitly archived |
| paused | canceled | cancel | Terminal unless explicitly archived |
| canceled | archived | archive | Final state; read-only |
| active | completed | natural completion | One-time schedule after success |
| completed | archived | archive | Final state; read-only |

## Execution State Transitions

| From | To | Trigger | Notes |
| --- | --- | --- | --- |
| queued | running | dispatcher start | Captures `started_at` |
| running | succeeded | success | Terminal; captures `finished_at` |
| running | failed | non-retriable error | Terminal; captures `finished_at` |
| running | retry_scheduled | retriable error | Computes `next_retry_at` |
| retry_scheduled | queued | retry time reached | Increments `attempt_number` |
| queued | canceled | schedule canceled | Terminal |
| running | canceled | manual abort | Terminal |

**Retry semantics**
- Retry is only allowed while `attempt_number < max_attempts`.
- `retry_scheduled` is used when backoff applies; otherwise transition directly to `queued`.
- On each failed attempt, increment `failure_count` and record `last_error_code/message`.

## Conditional Schedule Evaluation
- Conditional schedules define an explicit evaluation cadence (`evaluation_interval_*`).
- Predicate evaluation runs with a scheduled actor authorization context envelope and read-only
  Skills/Ops.
- When predicate result is `true`, an Execution is created at the evaluated time.
- When predicate result is `false`, no Execution is created; schedule remains `active`.
- Evaluation errors set `last_evaluation_status = error` and populate `last_evaluation_error_code`.

## Audit and Authority Notes
- All entities include `created_at` and actor attribution for provenance.
- Schedule and Execution live in Tier 1 (Postgres). TaskIntent remains Tier 1 until promoted by
  Letta (Tier 0) via explicit memory governance.
- All scheduled executions must pass through attention routing for any notifications.

## Alignment Checklist
- Manifesto: attention is sacred, actions bounded, truth explicit.
- Architecture doctrine: Tier authority and rebuildability respected.
- Security/trust boundaries: scheduled actor context enforced for all execution and predicate
  evaluation calls.
