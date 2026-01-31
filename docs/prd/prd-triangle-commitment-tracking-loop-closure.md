# PRD: Commitment Tracking & Loop Closure
## Turning Intent into Outcomes for Brain

---

## 1. Overview

### Feature Name
**Commitment Tracking & Loop Closure**

### Summary
Introduce a **commitment management layer** that tracks promises, tasks, follow-ups, and obligations over time — ensuring they are **closed, reviewed, or consciously renegotiated**, rather than silently forgotten.

This feature transforms Brain from a capture-and-remind system into an **outcome-oriented partner** that helps the human keep commitments to themselves and others.

---

## 2. Problem Statement

Most productivity systems fail not because tasks aren’t captured, but because:
- commitments decay silently
- reminders fire without context
- missed deadlines disappear without reflection
- no feedback loop exists between intention and reality

As a result:
- trust in the system erodes
- users compensate with anxiety or over-checking
- the system becomes archival, not transformational

Brain must **close loops**, not just open them.

---

## 3. Goals and Non-Goals

### Goals
- Treat reminders and tasks as first-class commitments
- Track commitment lifecycle from creation to resolution
- Detect and surface missed or stalled commitments
- Enable reflection, renegotiation, and learning
- Integrate with scheduling, memory, and attention systems

### Non-Goals
- Replacing full-featured task managers
- Enforcing productivity or moral judgment
- Automatic punitive escalation
- Optimizing for maximum task completion at all costs
- Recurring commitment schedules (out of scope for v1)

---

## 4. Design Principles

1. **Commitments represent intent**
2. **Missed commitments are signals, not failures**
3. **Nothing disappears without explanation**
4. **Closure matters more than completion**
5. **Reflection creates leverage**

---

## 5. Core Concepts

### 5.1 Commitment
A commitment is a promise that has:
- intent
- scope
- time relevance
- expected outcome

Examples:
- “Follow up with Alex”
- “Review proposal by Friday”
- “Think about this article later”

---

### 5.2 Commitment Lifecycle

States:
- `OPEN`
- `COMPLETED`
- `MISSED`
- `CANCELED`
- `RENEGOTIATED`

Commitments begin in `OPEN`.

Transitions are explicit and auditable.

---

### 5.3 Closure
A commitment is *closed* when:
- it is completed
- it is consciously canceled
- it is renegotiated with a new form

Silence is not closure.

---

## 6. Functional Requirements

### 6.1 Commitment Creation

Commitments may be created from any inbound signals:
- operator input (Signal, local agent)
- MCP tools and skills
- ingestion outcomes (email, iMessage, meeting transcripts, files, etc.)
- agent suggestions (subject to approval rules below)

Each commitment must store:
- description (single canonical text field; required)
- provenance_id (links to provenance record)
- due_by (optional single datetime, stored in UTC; rendered in user timezone)
- state (current lifecycle state)
- importance (int 1-3; operator or model supplied; default: 2)
- effort_provided (int 1-3; operator-specified; default: 2)
- effort_inferred (int 1-3; model-specified; optional)
- urgency (int 1-100; stored; derived from importance/effort/due_by)
- renegotiated_from_id (nullable)
- created_at / updated_at timestamps (UTC)
- last_progress_at (UTC, nullable)
- reviewed_at (UTC, nullable; set during weekly review)
- next_schedule_id (nullable; only when a schedule exists)
- related artifacts (notes, messages, threads)

Notes:
- Ownership is implicitly the operator (future support for external assignees is expected).
- effort_provided takes precedence over effort_inferred.
- Urgency is recalculated whenever importance, effort, or due_by changes; recalculation should validate the active
  follow-up schedule is still sensible.
- TODO: Define provenance schema and subsystem contract; CTLC depends on it.
- A derived summary field may be introduced later if descriptions become lengthy.

#### 6.1.1 Creation Authority & Confidence
- User-initiated signals create commitments directly.
- Agent suggestions require user approval unless confidence meets or exceeds a configurable threshold.
- Initial implementation: confidence is coerced to `0.0` at compare time (TODO: replace with a real model once historical
  data exists). This intentionally disables autonomous creation in v1.

#### 6.1.2 Scheduling Rules
- No schedule is created when `due_by` is absent.
- When `due_by` is present, a schedule may be created to support reminders/check-ins.
- Commitments without `due_by` must be surfaced in the next review (see §9.1).
- Date-only `due_by` defaults to `23:59:59` in the operator’s configured timezone, then stored in UTC.
- When `due_by` is absent, urgency calculation assumes `due_by = now + 7 days`.
- No recurring commitment schedules in v1.

#### 6.1.3 Validation & Dedupe
- Minimum required input is `description`; other fields are optional at creation time.
- Defaults: `state` is `OPEN`; importance and effort default to 2; urgency is computed at creation time.
- Dedupe is LLM-driven using a configurable confidence threshold.
- Dedupe proposals must include a short summary (default 20 words) and require operator confirmation via prompt/reply.
- Dedupe evaluation is performed per-commitment using the full set of other commitments as comparison candidates.
- Dedupe proposals are not persisted beyond surfacing and operator decision.
- A second duplicate check is performed during weekly review prep to surface missed duplicates for reconciliation.

#### 6.1.4 Scheduler Linkage
- Commitments are a separate domain from scheduling. Scheduling uses `TaskIntent` + `Schedule` to encode execution, and
  commitments link to schedules, not to task intents directly.
- Scheduler callbacks provide `schedule_id`; the commitment module resolves the commitment via `next_schedule_id`. The
  scheduler remains agnostic of commitment foreign keys.
- When a commitment is assigned `due_by` (at creation or later), create a new `TaskIntent` and `Schedule` immediately.
- Commitment follow-ups are one-time schedules (reminders/checks/escalation points), not recurring schedules.
- When `due_by` changes, update the existing schedule in place (no new schedule).
- When a commitment is canceled or renegotiated, remove any associated schedules.
- Commitments store `next_schedule_id` (nullable) as a convenience pointer to the next scheduled follow-up; the scheduler
  service already maintains its own audit history.
- At most one active follow-up schedule exists per commitment at any time.
- CTLC uses the scheduler service interface only; it must not directly manipulate scheduler database tables.

---

### 6.2 Tracking & State Management

The system must:
- track current state
- record state transitions
- timestamp all changes
- associate outcomes with actions taken
- gate autonomous state transitions by confidence
- store transition history in normalized database table(s); no embedded state_history field on the commitment

Suggested normalized table (minimum fields):
- commitment_id
- from_state
- to_state
- transitioned_at (UTC)
- actor (user/system)
- reason/context (text)
- confidence (float)

#### 6.2.1 Transition Authority
- `MISSED` is applied autonomously when due time passes without closure.
- All other transitions are eligible for autonomous application if their confidence meets or exceeds a configurable
  threshold.
- When confidence is below the threshold, the system must propose the transition and wait for user confirmation.
- Confidence is assessed at transition time.
- Initial implementation: confidence is forced to `0.0` at assessment time (TODO: replace with real confidence model).

#### 6.2.2 Transition Rules
- Valid states: `OPEN`, `COMPLETED`, `MISSED`, `CANCELED`, `RENEGOTIATED`.
- Any state may transition to any other state.
- User-initiated transitions override pending proposals and cancel any scheduled follow-ups.
- `MISSED` is not terminal; it may transition to `COMPLETED`, `CANCELED`, or `RENEGOTIATED`.
- `RENEGOTIATED` creates a new linked commitment and inherits provenance and related artifacts by default.

---

### 6.3 Miss Detection

If a commitment passes its due time without closure:
- mark as `MISSED` immediately (no grace period)
- record context (what happened)
- route signal via Attention Router (policy-controlled)

Commitments with no `due_by`:
- are valid
- are never auto-marked `MISSED`
- do not require a schedule
- must be surfaced in the next review

---

### 6.4 Loop Closure Prompts

For missed or long-running commitments, Brain may:
- ask what happened
- suggest deferral
- suggest renegotiation
- suggest cancellation

These prompts are:
- respectful
- non-judgmental
- optional

Prompt delivery rules:
- Channel: Signal only (current implementation scope).
- Urgency is model-derived and mapped into the Attention Router.
- Commitments with no `due_by` only prompt within the weekly review flow.

---

### 6.5 Commitment Progress

Commitment progress is captured as a separate record to avoid mutating commitments for every related signal.

Minimum CommitmentProgress fields:
- progress_id
- commitment_id
- provenance_id
- occurred_at (UTC)
- summary (short)
- snippet (optional)
- metadata (optional)

Commitments may include a derived `last_progress_at` field for efficient reasoning without extra joins.

Progress is recorded only when the agent determines that related data constitutes actual progress.

---

### 6.6 Canonical Storage (Postgres) and Backup

Postgres is the canonical Tier 0 source of truth for commitments, events, progress, and provenance.
There is no dual-write, syncing, or rebuild path from Obsidian. Postgres must be backed up according to Tier 0 policy.

#### 6.6.1 Backup Expectations
- Backups are required for Tier 0 durability and recovery.
- Backup frequency, retention, and restore procedures are defined by the system backup policy.

#### 6.6.2 Optional Obsidian Exports (Non-Canonical)
- Exporting commitment data to Obsidian is out of scope for v1.
- Any future export is read-only, best-effort, and does not affect source of truth.

#### 6.6.3 Urgency Calculation (Tier 0)
Urgency is stored and recalculated when importance, effort, or due_by changes.

Inputs:
- importance (int 1-3; default 2)
- effort (int 1-3; default 2)
- due_by (datetime, optional)
- now (current time in UTC)

Effort hours map:
- 1 → 0.5 hours
- 2 → 2 hours
- 3 → 8 hours

Time pressure:
- time_left_hours = max(0, (due_by - now) in hours)
- if due_by is null, assume due_by = now + 7 days for urgency calculation
- time_pressure = clamp(1 - (time_left_hours / max(1, effort_hours * 4)), 0, 1)

Urgency score:
- base_importance = importance / 3
- base_effort = effort / 3
- urgency_raw = (0.4 * base_importance) + (0.4 * time_pressure) + (0.2 * base_effort)
- urgency = round(1 + (urgency_raw * 99))  # 1-100

---

## 7. Integration Points

### 7.1 Scheduling System
- Commitments may schedule reminders or checks
- Scheduler callbacks provide `schedule_id`; the commitment module resolves linkage via `next_schedule_id`.
- Scheduler callbacks invoke commitment module public interfaces only
- Scheduler callbacks may trigger commitment evaluation logic but may not directly set commitment state
- Commitment schedules are derived from commitment data and are not canonical

---

### 7.2 Attention Router
- All commitment-related outbound messaging must route through the Attention Router (no direct sends).
- Signal is the only supported outbound channel in v1.
- Routing uses model-derived urgency (and other router inputs) rather than a static priority tier.
- Missed commitments have no grace period and are routed immediately based on urgency.
- No quiet-hours overrides in v1; the Attention Router enforces existing policies.
- Repeated misses may escalate prompt frequency and may be summarized in weekly reviews.

---

### 7.3 Configuration
- Commitments are configured in `brain.yml` under `commitments`.
- `commitments.autonomous_transition_confidence_threshold` controls autonomous transition eligibility.
- `commitments.autonomous_creation_confidence_threshold` controls autonomous creation eligibility (default: `0.9`).
- `commitments.dedupe_confidence_threshold` controls dedupe proposal eligibility (default: `0.8`).
- `commitments.dedupe_summary_length` controls dedupe summary word limit (default: `20`).
- `commitments.review_day` controls weekly review day (default: `Saturday`).
- `commitments.review_time` controls weekly review time (default: `10:00`).
- All user-facing dates/times are interpreted in the operator-configured timezone.

---

## 8. Observability & Audit

For each commitment, store audit records in normalized database tables:
- creation source
- full lifecycle history (state transitions)
- resolution notes (optional)
- related notifications
- decision type (user vs system)
- reason/context (free text)
- evidence/inputs (links to related artifacts)

Retention:
- Configurable retention window; empty/0/null means indefinite.

---

## 9. Review & Reflection

### 9.1 Periodic Reviews

Weekly reviews are generated automatically (via TaskIntent + Schedule) and include:
- completed commitments
- missed commitments
- commitments changed since the last review
- commitments with no `due_by`
- potential duplicate commitments flagged during review prep

Review format:
- structured data summary
- natural language summary

Reviews are surfaced as:
- Signal message (primary channel)

If there are no changes, the review still reports that there is nothing new to review and logs the confirmation.
`reviewed_at` is updated at least during weekly review, and may be updated by other explicit review prompts.

---

### 9.2 Learning Signals

The system may infer:
- unrealistic deadlines
- overcommitment patterns
- preferred renegotiation styles

These are *proposals*, not automatic behavior changes.

---

## 10. Risks and Mitigations

### Risk: Guilt or Pressure
Mitigation:
- neutral language
- opt-out prompts
- focus on clarity, not judgment

### Risk: Notification Fatigue
Mitigation:
- attention routing
- batching
- prioritization by impact

---

## 11. Success Metrics

- Increased commitment closure rate
- Fewer forgotten tasks
- Higher trust in reminders
- Reduced anxiety from open loops
- Meaningful reflection captured over time

---

## 12. Definition of Done

- [ ] Commitment data model defined
- [ ] Lifecycle state tracking implemented
- [ ] Miss detection working
- [ ] Loop-closure prompts integrated
- [ ] Review summaries generated
- [ ] Attention Router fully integrated
- [ ] Tier 0 backup policy confirmed and operational

---

## 13. Alignment with Brain Manifesto

- **Everything Compounds:** closed loops create leverage
- **Attention Is Sacred:** prompts are intentional
- **Truth Is Explicit:** commitments don’t vanish silently
- **Memory Is Curated:** patterns, not raw tasks, become memory

---

_End of PRD_
