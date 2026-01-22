<!--
Docblock:
- File: scheduling-architecture-note.md
- Purpose: Define adapter boundaries and end-to-end data flow for scheduled task execution.
- Scope: Scheduled & Timed Tasks architecture (Epic 01 / Milestone 01).
-->
# Scheduling Architecture Note

## Purpose
Define the adapter boundaries between Brain and scheduler providers and document the end-to-end
data flow for scheduled task execution. This note is provider-agnostic and aligns with the
scheduled actor context, attention routing, and audit requirements.

## Core Boundary Principles
- Schedules are data, not configuration; Brain owns schedule intent and state.
- Scheduler providers are implementation details and must be interchangeable.
- All scheduled executions run with a constrained, scheduled actor context.
- No scheduled execution may bypass attention routing or authorization checks.

## Component Boundaries and Ownership

### First-Party (Brain-Owned)
- Schedule Management API (create/update/pause/resume/delete/run-now).
- Schedule Service (validation, persistence, state transitions).
- Execution Dispatcher (creates executions, invokes agent, records outcomes).
- Authorization Context Envelope (scheduled actor constraints).
- Attention Router (notification gating and batching).
- Audit Logging (schedule changes, executions, side effects).

### Provider (Scheduler Implementation)
- Triggering scheduled callbacks based on registered schedules.
- Retry scheduling signals based on dispatcher responses.
- Delivery guarantees within configured tolerances.
- Operational metrics for scheduler health.

## End-to-End Data Flow (Bullet Diagram)

1. **Intent creation** (Brain): A TaskIntent is created and persisted (immutable).
2. **Schedule creation** (Brain): A Schedule is validated and stored with explicit fields.
3. **Adapter registration** (Brain -> Provider): Brain registers or updates schedule metadata
   with the scheduler adapter (provider-specific translation only).
4. **Trigger event** (Provider -> Adapter): Provider triggers a schedule callback at `next_run_at`.
5. **Execution creation** (Dispatcher): Dispatcher creates an Execution record (queued),
   binds scheduled actor context, and sets correlation IDs.
6. **Execution start** (Dispatcher -> Agent): Dispatcher invokes the agent with:
   - TaskIntent summary/details
   - Schedule metadata (type, cadence, next/last run)
   - Execution metadata (attempt, retry/backoff, scheduled_for)
   - Authorization context envelope (scheduled actor, constrained autonomy)
7. **Agent decision** (Agent): Agent decides on actions, drafts outputs, and may propose memory
   (never direct promotion).
8. **Attention routing** (Attention Router): Any notification or outbound message is gated
   by attention policy (quiet hours, batching, escalation thresholds).
9. **Side effects** (Ops/Skills): Only authorized, context-scoped operations run; all are
   auditable.
10. **Completion** (Dispatcher): Dispatcher records outcome, updates schedule next_run_at,
    and emits audit entries.

## Trust Boundaries and Gates
- **Boundary 1: Scheduler Provider -> Brain**
  - Provider callbacks are untrusted input; dispatcher validates schedule identity,
    state, and timing.
- **Boundary 2: Dispatcher -> Agent**
  - Agent receives only the scoped, scheduled actor context; no implicit elevation.
- **Boundary 3: Agent -> Ops/Skills**
  - Authorization checks enforce read/write scope; predicate evaluation is read-only.
- **Boundary 4: Agent -> Attention Router**
  - Notifications must pass attention routing; silent outcomes are allowed.

## Authorization Context (Scheduled Actor)
- Actor type: `scheduled`
- Privilege level: constrained
- Autonomy: limited; no direct memory promotion
- Context envelope passed on every invocation and evaluation

## Error and Retry Ownership
- **Dispatcher owns**:
  - Execution creation, status transitions, and retry policy enforcement.
  - Determining retriable vs terminal failures.
  - Updating schedule failure_count and last_run_status.
- **Provider owns**:
  - Scheduling the next callback based on dispatcher response.
  - Operational retry of callback delivery (transport-level issues only).

## Audit Logging Responsibilities
- **Schedule audits**: Brain logs all create/update/pause/resume/delete/run-now changes
  with actor attribution.
- **Execution audits**: Dispatcher logs execution start/end, outcome, retry decisions,
  and side effects.
- **Attention audits**: Attention Router logs notification decisions and suppressions.

## Adapter Interface Summary (Provider-Agnostic)
- `register_schedule(schedule_id, schedule_payload)`
- `update_schedule(schedule_id, schedule_payload)`
- `pause_schedule(schedule_id)`
- `resume_schedule(schedule_id)`
- `delete_schedule(schedule_id)`
- `trigger_callback(schedule_id, scheduled_for, *, trace_id=None, trigger_source="scheduler_callback")`
- `trigger_source` indicates the origin of the callback (e.g., `run_now` vs the scheduler cadence).

## Alignment Notes
- **Attention is sacred**: all notifications routed and suppressible.
- **Actions are bounded**: scheduled actor context constrains authority.
- **Truth is explicit**: intent, schedule, and execution data are auditable.
- **Rebuildability**: provider state can be reconstructed from Tier 1 data.
