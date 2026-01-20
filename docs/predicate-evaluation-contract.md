<!--
Docblock:
- File: predicate-evaluation-contract.md
- Purpose: Define the contract for conditional schedule predicate evaluation.
- Scope: Scheduled & Timed Tasks (Epic 01 / Milestone 01).
-->
# Predicate Evaluation Contract

## Purpose
Define the provider-agnostic contract for evaluating conditional schedule predicates. Predicate
evaluation is read-only, deterministic, and runs under a constrained `scheduled` actor context.
It must never invoke side-effecting Skills/Ops or promote memory. Evaluation results determine
whether a conditional schedule triggers an Execution or defers until the next cadence.

## Scope
- Predicate input schema and allowed operators.
- Evaluation cadence requirements and scheduling semantics.
- Read-only Skills/Ops constraints and authorization context envelope.
- Evaluation outcomes, error handling, and schedule state effects.
- Required audit fields for each evaluation attempt.

## Non-Goals
- Predicate persistence schema or migrations.
- Scheduler provider transport or callback details.
- Execution invocation payloads (see `docs/execution-invocation-contract.md`).

## Domain References
- `docs/scheduling-domain-model.md`
- `docs/scheduling-architecture-note.md`
- `docs/schedule-management-api-contract.md`
- `docs/prd-scheduled-timed-tasks.md`

## Core Principles
- Read-only only: no side effects, no mutations, no memory promotion.
- Deterministic: same inputs yield the same output for a given evaluation time.
- Inspectable: all inputs and outcomes are auditable with explicit fields.
- Authorization-aware: evaluation runs as `scheduled` actor with constrained authority.

## Predicate Input Schema

### PredicateDefinition
- `predicate_subject` (required; capability/skill/op identifier)
- `predicate_operator` (required; see Operators)
- `predicate_value` (required unless operator is `exists`)
- `predicate_value_type` (required; `string`, `number`, `boolean`, `timestamp`)
- `predicate_context` (optional; constrained metadata, no JSON blobs)

### Operators
Allowed operators (no custom operators without explicit review):
- `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `exists`, `matches`

**Operator semantics**
- `exists`: returns true when the subject resolves to a non-empty value; ignores
  `predicate_value`.
- `matches`: string match using a constrained, safe pattern syntax; the evaluator must
  explicitly reject unbounded regex patterns.

## Evaluation Cadence and Scheduling Semantics

### Cadence Requirements
Conditional schedules must define evaluation cadence at creation time:
- `evaluation_interval_count` (required; > 0)
- `evaluation_interval_unit` (`minute`, `hour`, `day`, `week`)
- `timezone` (required; IANA timezone for cadence calculations)

### Scheduling Semantics
- The scheduler triggers evaluations at each cadence boundary.
- Evaluation time is the authoritative timestamp for result interpretation.
- Drift tolerance is handled by the scheduler provider; Brain uses the evaluation timestamp
  from the callback payload.
- If evaluation is delayed, the evaluation still runs and records the actual evaluation time.

## Authorization Context Envelope

### Required Context
**ActorContext**
- `actor_type` (fixed: `scheduled`)
- `actor_id` (nullable)
- `channel` (fixed: `scheduled`)
- `privilege_level` (fixed: constrained)
- `autonomy_level` (fixed: limited)
- `trace_id` (required)
- `request_id` (optional)

### Enforcement Rules
- Predicate evaluation must reject any attempt to run without `scheduled` actor context.
- Evaluation cannot elevate privileges or override context.
- Skills/Ops invoked must enforce read-only capability flags.

## Read-Only Skills/Ops Constraints
- Only capabilities explicitly marked read-only are allowed.
- Any capability that can create, update, delete, or send must be rejected.
- If a subject maps to a non-read-only capability, evaluation fails with `forbidden`.
- No memory promotion or direct note writes are allowed during evaluation.

## Evaluation Result Contract

### PredicateEvaluationRequest
- `evaluation_id` (required; stable id for idempotency)
- `schedule_id` (required)
- `task_intent_id` (required)
- `evaluation_time` (required timestamp)
- `predicate` (PredicateDefinition)
- `actor_context` (ActorContext)
- `provider_name` (required; scheduler identifier)
- `provider_attempt` (required int; delivery attempt)
- `correlation_id` (required; for audit)

### PredicateEvaluationResult
- `status` (`true`, `false`, `error`)
- `result_code` (required; machine-readable)
- `message` (optional; human-readable summary)
- `observed_value` (optional; string/number/boolean/timestamp)
- `evaluated_at` (required timestamp)
- `error` (optional; only for `error`)
  - `error_code`
  - `error_message`

## Schedule State Effects
- `status = true`: create an Execution for `evaluation_time` and advance schedule state
  normally.
- `status = false`: do not create an Execution; schedule remains `active`.
- `status = error`: do not create an Execution; schedule remains `active`, and
  `last_evaluation_status = error` with `last_evaluation_error_code`.

## Error Handling
Errors are explicit and non-silent. Common error codes:
- `invalid_predicate`
- `subject_not_found`
- `operator_not_supported`
- `value_type_mismatch`
- `forbidden` (read-only or authorization violation)
- `evaluation_failed`
- `timeout`

## Audit Fields (Required)
Each evaluation attempt must be recorded with explicit fields (no JSON blobs):
- `evaluation_id`
- `schedule_id`
- `task_intent_id`
- `actor_type`, `actor_id`, `channel`
- `predicate_subject`
- `predicate_operator`
- `predicate_value`
- `predicate_value_type`
- `evaluation_time`
- `evaluated_at`
- `status`
- `result_code`
- `error_code` (nullable)
- `error_message` (nullable)
- `observed_value` (nullable)
- `provider_name`
- `provider_attempt`
- `correlation_id`

## Determinism and Inspectability
- Predicate evaluation must not depend on mutable global state without explicit subject
  versioning.
- Inputs, subject resolution, and results must be reproducible from stored fields.

## Alignment Checklist
- Read-only enforcement explicit: yes.
- Scheduled actor context required: yes.
- Cadence and outcomes specified: yes.
- Side effects and memory promotion prohibited: yes.
