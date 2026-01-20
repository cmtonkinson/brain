<!--
Docblock:
- File: execution-invocation-contract.md
- Purpose: Define the scheduler callback and agent invocation contract for scheduled executions.
- Scope: Scheduled & Timed Tasks (Epic 01 / Milestone 01).
-->
# Execution Invocation Contract

## Purpose
Define the provider-agnostic contract for invoking the Brain agent when a schedule fires. This
contract specifies scheduler callback payloads, dispatcher responsibilities, agent invocation
payloads, retry/backoff metadata, and audit fields. All scheduled executions run with a constrained
`scheduled` actor context and must respect attention routing.

## Scope
- Scheduler callback payload (provider -> dispatcher).
- Dispatcher responsibilities and validation gates.
- Agent invocation payload (dispatcher -> agent).
- Retry/backoff metadata and failure semantics.
- Outcome envelope and idempotency guidance.
- Audit logging fields per invocation.

## Non-Goals
- Provider-specific transport or webhook details.
- Persistence schema or migrations.
- Execution routing for non-scheduled actors.

## Domain References
- `docs/scheduling-domain-model.md`
- `docs/scheduling-architecture-note.md`
- `docs/schedule-management-api-contract.md`
- `docs/prd-scheduled-timed-tasks.md`

## Roles and Responsibilities

### Scheduler Provider
- Triggers callbacks at scheduled times.
- Delivers callback payloads with stable IDs.
- Retries callback delivery for transport failures only.

### Dispatcher (Brain-owned)
- Validates callback payloads and schedule state.
- Creates or reuses an Execution record and assigns correlation IDs.
- Invokes the agent with a scheduled actor context.
- Records outcomes, retry decisions, and audit entries.

### Agent (Brain-owned)
- Interprets TaskIntent and Schedule context.
- Proposes actions; all notifications must go through attention routing.
- Returns an explicit outcome (success, failure, deferred).
- Never promotes memory directly.

## Scheduler Callback Payload (Provider -> Dispatcher)

**CallbackPayload**
- `callback_id` (required, stable ID for idempotency)
- `schedule_id` (required)
- `scheduled_for` (required timestamp; intended run time)
- `emitted_at` (required timestamp; provider emission time)
- `provider_name` (required string identifier)
- `provider_attempt` (required int; delivery attempt count)
- `provider_trace_id` (optional; provider correlation)
- `schedule_version` (optional; provider-side version or hash)

**Validation Rules**
- `schedule_id` must map to an active schedule in Brain.
- `scheduled_for` must be within allowed drift tolerance from Brain schedule metadata.
- Duplicate `callback_id` must be treated as idempotent replays.
- `scheduled` actor context is enforced; no actor override.

## Dispatcher Responsibilities

**Execution creation**
- Create or reuse an Execution record keyed by (`schedule_id`, `scheduled_for`).
- Set `status = queued`, `attempt_number`, `max_attempts`, and retry policy.
- Generate a stable `correlation_id` for audit and tracing.

**Invocation gate**
- Verify schedule state is `active` (or `paused` only when run-now is used).
- Validate schedule definition and cadence before invoking the agent.
- Reject or defer execution if schedule is `canceled`, `archived`, or `completed`.

**Outcome handling**
- Update execution status and schedule fields (last_run_at, last_run_status, failure_count).
- Decide retriable vs terminal failures.
- Emit audit entries for start, outcome, and retry decisions.

## Agent Invocation Payload (Dispatcher -> Agent)

**ExecutionInvocationRequest**
- `execution`
  - `id` (execution_id)
  - `schedule_id`
  - `task_intent_id`
  - `scheduled_for`
  - `attempt_number`
  - `max_attempts`
  - `backoff_strategy` (`fixed`, `exponential`, `none`)
  - `retry_after` (optional timestamp; next retry time)
  - `correlation_id`
- `task_intent`
  - `summary`
  - `details` (optional)
  - `origin_reference` (optional)
- `schedule`
  - `schedule_type`
  - `timezone`
  - `definition` (typed fields only; no JSON)
  - `next_run_at` (optional)
  - `last_run_at` (optional)
  - `last_run_status` (optional)
- `actor_context`
  - `actor_type` (fixed: `scheduled`)
  - `actor_id` (nullable)
  - `channel` (fixed: `scheduled`)
  - `privilege_level` (fixed: constrained)
  - `autonomy_level` (fixed: limited)
  - `trace_id` (required)
  - `request_id` (optional)
- `execution_metadata`
  - `actual_started_at` (timestamp)
  - `trigger_source` (`scheduler_callback` or `run_now`)
  - `callback_id` (from provider, if available)

## Outcome Envelope (Agent -> Dispatcher)

**ExecutionInvocationResult**
- `status` (`success`, `failure`, `deferred`)
- `result_code` (required; short machine-readable code)
- `message` (optional; human-readable summary)
- `attention_required` (required boolean; true only when a routed notification exists)
- `side_effects_summary` (optional; short string, no JSON payloads)
- `retry_hint` (optional; only for `deferred`)
  - `retry_after` (timestamp)
  - `backoff_strategy` (`fixed`, `exponential`, `none`)
- `error` (optional; only for `failure`)
  - `error_code`
  - `error_message`

**Outcome semantics**
- `success`: execution completed; schedule advances normally.
- `failure`: non-retriable; execution becomes terminal.
- `deferred`: retriable; dispatcher schedules retry when allowed.

## Retry and Backoff Metadata
- Retry is allowed only when `attempt_number < max_attempts`.
- Backoff is controlled by dispatcher policy (`fixed`, `exponential`, `none`).
- Dispatcher records `next_retry_at` and `retry_backoff_strategy` on the Execution.
- Provider is only responsible for delivering callbacks; it must not decide Brain retry logic.

## Idempotency Guidance
- `callback_id` is the primary idempotency key for provider callbacks.
- Dispatcher must treat duplicate `callback_id` as a replay and reuse the same Execution record.
- Agent invocations are idempotent by `execution_id`; repeats must not duplicate side effects.
- If an execution is already terminal, dispatcher returns the existing outcome without re-invoking.

## Audit Logging (Required Fields)
For every invocation attempt, record an audit entry with explicit fields (no JSON blobs):
- `execution_id`
- `schedule_id`
- `task_intent_id`
- `correlation_id`
- `callback_id` (if available)
- `actor_type`, `actor_id`, `channel`
- `scheduled_for`
- `actual_started_at`
- `finished_at`
- `status`
- `attempt_number`
- `max_attempts`
- `retry_backoff_strategy`
- `next_retry_at` (nullable)
- `result_code`
- `error_code` (nullable)
- `error_message` (nullable)
- `attention_required`

## Attention Routing and Authorization Notes
- All user-facing outputs must pass through the Attention Router.
- Scheduled executions run with constrained authority and may not promote memory directly.
- Skills/Ops invoked during execution must enforce authorization based on `scheduled` context.

## Alignment Checklist
- Scheduler-agnostic callback and invocation contract: defined.
- Actor context constrained to `scheduled`: enforced.
- Retry/backoff metadata and failure handling: explicit.
- Auditability: required fields enumerated.
