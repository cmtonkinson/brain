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
- provenance_id (links to provenance record; see src/ingestion/provenance.py)
- due_by (optional single datetime, stored in UTC; rendered in user timezone)
- state (current lifecycle state: OPEN | COMPLETED | MISSED | CANCELED)
- importance (int 1-3; operator or model supplied; default: 2)
- effort_provided (int 1-3; operator-specified; default: 2)
- effort_inferred (int 1-3; model-specified; optional)
- urgency (int 1-100; stored; derived from importance/effort/due_by; experimental)
- created_at / updated_at timestamps (UTC)
- last_progress_at (UTC, nullable)
- last_modified_at (UTC, nullable; updated when description/due_by/importance/effort changes)
- ever_missed_at (UTC, nullable; set once when first marked MISSED; for analytics)
- presented_for_review_at (UTC, nullable; updated each time commitment appears in review)
- reviewed_at (UTC, nullable; updated when operator engages with commitment in review)
- next_schedule_id (nullable; foreign key to active schedule)
- related artifacts (notes, messages, threads) [TBD: schema deferred]

Notes:
- Ownership is implicitly the operator (future support for external assignees is expected).
- effort_provided takes precedence over effort_inferred.
- Urgency is recalculated whenever importance, effort, or due_by changes; recalculation should validate the active
  follow-up schedule is still sensible (e.g., due tomorrow with a follow-up scheduled days later is invalid; urgency
  near 99 with a follow-up scheduled for next week is likely invalid).
- Provenance system implemented in src/ingestion/provenance.py
- Urgency calculation (§6.6.3) is experimental and subject to tuning based on real-world usage
- `last_modified_at` tracks substantive changes (description, due_by, importance, effort) for renegotiation analysis
- `ever_missed_at` is immutable once set; provides "has ever been late" signal for pattern analysis
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
- Scheduler callbacks provide `schedule_id`; the commitment module resolves the commitment via the linking table.
  The scheduler remains agnostic of commitment foreign keys.
- When a commitment is assigned `due_by` (at creation or later), create a new `TaskIntent` and `Schedule` immediately.
- Commitment follow-ups are one-time schedules (reminders/checks/escalation points), not recurring schedules.
- When `due_by` changes, update the existing schedule in place (no new schedule).
- When a commitment is canceled or completed, remove any associated schedules.
- Commitments store `next_schedule_id` (nullable) as a convenience pointer to the next scheduled follow-up; the scheduler
  service already maintains its own audit history.
- At most one active follow-up schedule exists per commitment at any time.
- Follow-up schedules are never shared across commitments.
- CTLC uses the scheduler service interface only; it must not directly manipulate scheduler database tables.

**Scheduler Callback Edge Cases:**
TODO: Document cleanup logic for stale schedules when user transitions override pending schedules
(e.g., callback fires and marks MISSED, then user immediately marks COMPLETED before callback completes).
Comprehensive logging should make diagnosis straightforward if this occurs in practice.

**Linking Table Schema:**
Use a bidirectional linking table to maintain referential integrity between commitments and schedules:

```sql
CREATE TABLE commitment_schedules (
    commitment_id BIGINT NOT NULL REFERENCES commitments(commitment_id) ON DELETE CASCADE,
    schedule_id BIGINT NOT NULL REFERENCES schedules(schedule_id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    PRIMARY KEY (commitment_id, schedule_id)
);

CREATE INDEX idx_cs_schedule_id ON commitment_schedules(schedule_id) WHERE is_active = TRUE;
CREATE INDEX idx_cs_commitment_id ON commitment_schedules(commitment_id) WHERE is_active = TRUE;
```

When callbacks fire with `schedule_id`, resolve via:
```sql
SELECT c.* FROM commitments c
JOIN commitment_schedules cs ON c.commitment_id = cs.commitment_id
WHERE cs.schedule_id = ? AND cs.is_active = TRUE;
```

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
- Valid states: `OPEN`, `COMPLETED`, `MISSED`, `CANCELED`.
- Any state may transition to any other state.
- User-initiated transitions override pending proposals and cancel any scheduled follow-ups.
- `MISSED` is not terminal; it may transition to `COMPLETED`, `CANCELED`, or back to `OPEN`.
- State changes to description, due_by, importance, or effort update `last_modified_at` for renegotiation tracking.

#### 6.2.3 State Transition Audit Table

All state transitions are recorded in a normalized audit table for observability and analysis:

```sql
CREATE TABLE commitment_state_transitions (
    transition_id BIGSERIAL PRIMARY KEY,
    commitment_id BIGINT NOT NULL REFERENCES commitments(commitment_id) ON DELETE CASCADE,
    from_state VARCHAR(20) NOT NULL,
    to_state VARCHAR(20) NOT NULL,
    transitioned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor VARCHAR(20) NOT NULL, -- 'user' | 'system'
    reason TEXT,
    context JSONB, -- structured data about the transition
    confidence NUMERIC(3,2), -- 0.00 to 1.00, nullable
    provenance_id BIGINT REFERENCES provenance(provenance_id),

    CONSTRAINT valid_states CHECK (
        from_state IN ('OPEN', 'COMPLETED', 'MISSED', 'CANCELED')
        AND to_state IN ('OPEN', 'COMPLETED', 'MISSED', 'CANCELED')
    ),
    CONSTRAINT valid_actor CHECK (actor IN ('user', 'system')),
    CONSTRAINT valid_confidence CHECK (
        confidence IS NULL OR (confidence >= 0.00 AND confidence <= 1.00)
    )
);

-- Primary access pattern: Get history for a commitment
CREATE INDEX idx_cst_commitment_id
    ON commitment_state_transitions(commitment_id, transitioned_at DESC);

-- Query for all transitions by state
CREATE INDEX idx_cst_to_state
    ON commitment_state_transitions(to_state, transitioned_at DESC);

-- Audit queries: Find all system-initiated transitions
CREATE INDEX idx_cst_actor
    ON commitment_state_transitions(actor, transitioned_at DESC);

-- Analytics: Confidence-based queries
CREATE INDEX idx_cst_confidence
    ON commitment_state_transitions(confidence) WHERE confidence IS NOT NULL;
```

Retention enforcement (if `audit_retention_days > 0`):
```sql
DELETE FROM commitment_state_transitions
WHERE transitioned_at < NOW() - INTERVAL '? days';
```

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
- suggest due date changes
- suggest cancellation
- surface for review

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

**Note:** This urgency calculation is experimental and subject to tuning based on real-world usage patterns.
The weights (0.4, 0.4, 0.2) and time buffer multiplier (4x effort) are initial estimates and may be adjusted
as data accumulates.

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
- `commitments.batch_reminder_time` controls daily batch reminder delivery time (default: `06:00`).
- `commitments.audit_retention_days` controls audit retention window in days (default: `0` for indefinite).
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
- Configurable retention window; `commitments.audit_retention_days` of `0` means indefinite.

---

## 9. Review & Reflection

### 9.1 Periodic Reviews

Weekly reviews are generated automatically (via TaskIntent + Schedule) and include:
- completed commitments
- missed commitments
- commitments changed since the last review (via `last_modified_at`)
- commitments with no `due_by`
- potential duplicate commitments flagged during review prep

Review format:
- structured data summary
- natural language summary

Reviews are surfaced as:
- Signal message (primary channel)

If there are no changes, the review still reports that there is nothing new to review and logs the confirmation.

Each commitment included in a review has `presented_for_review_at` updated to the review generation time.
When the operator engages with the review, `reviewed_at` is updated to reflect actual review completion.

Commitments where `presented_for_review_at > reviewed_at` indicate presentation without engagement.

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
- attention routing with urgency-based prioritization
- daily batching at configurable time (default 06:00 via `commitments.batch_reminder_time`)
- weekly review consolidation
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

- [x] Provenance system implemented (src/ingestion/provenance.py)
- [ ] Commitment data model defined (including tracking timestamps)
- [ ] Commitment-schedule linking table implemented
- [ ] State transition audit table implemented
- [ ] Lifecycle state tracking implemented
- [ ] Miss detection working
- [ ] Loop-closure prompts integrated
- [ ] Review summaries generated (with presented_for_review_at / reviewed_at)
- [ ] Attention Router fully integrated
- [ ] Batch reminder scheduling configured
- [ ] Urgency calculation implemented (marked experimental)

---

## 13. Alignment with Brain Manifesto

- **Everything Compounds:** closed loops create leverage
- **Attention Is Sacred:** prompts are intentional
- **Truth Is Explicit:** commitments don’t vanish silently
- **Memory Is Curated:** patterns, not raw tasks, become memory

---

_End of PRD_
