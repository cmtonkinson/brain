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
- “Daily brief at 8am”
- “Think about this article later”

---

### 5.2 Commitment Lifecycle

States:
- `OPEN`
- `IN_PROGRESS`
- `COMPLETED`
- `MISSED`
- `DEFERRED`
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

Commitments may be created from:
- user requests (“remind me…”)
- scheduled tasks
- ingestion outcomes
- agent suggestions (with confirmation)

Each commitment must store:
- description (single canonical text field)
- provenance (who/what created it, and via which channel)
- due_by (optional single datetime, stored in UTC; rendered in user timezone)
- state (current lifecycle state)
- priority_tier (`high` or `low`)
- created_at / updated_at timestamps
- next_schedule_id (link to the *next* scheduled reminder/check in the scheduling system)
- related artifacts (notes, messages, threads)

Notes:
- Ownership is implicitly the operator (future support for external assignees is expected).
- A derived summary field may be introduced later if descriptions become lengthy.

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
- No disallowed transitions (any state may transition to any other state).
- User-initiated transitions override pending proposals and cancel any scheduled follow-ups.
- `MISSED` is not terminal; it may transition to `COMPLETED`, `CANCELED`, or `RENEGOTIATED`.
- `RENEGOTIATED` is terminal for the original commitment; a new linked commitment is created with revised terms.

---

### 6.3 Miss Detection

If a commitment passes its due time without closure:
- mark as `MISSED`
- record context (what happened)
- route signal via Attention Router (policy-controlled)

Commitments with no `due_by`:
- are valid
- must still have a `next_schedule_id`
- are never auto-marked `MISSED`

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
- High priority: prompt immediately when triggered.
- Low priority: batch prompts.
- Commitments with no `due_by` only prompt on scheduled checks.

---

## 7. Integration Points

### 7.1 Scheduling System
- Commitments may schedule reminders or checks
- Schedules reference commitment IDs
- Schedule execution updates commitment state

---

### 7.2 Attention Router
- Controls when closure prompts surface
- Batches low-urgency follow-ups
- Escalates repeated misses carefully

---

### 7.3 Memory Promotion
- Stable commitments or patterns may be proposed as memory
- Only Letta may promote patterns into durable memory

---

### 7.4 Configuration
- Commitments are configured in `brain.yml` under `commitments`.
- `commitments.autonomous_transition_confidence_threshold` controls autonomous transition eligibility.

---

## 8. Observability & Audit

For each commitment, store audit records in a normalized database table and mirror them into Obsidian:
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

Weekly reviews are generated automatically and include:
- completed commitments
- missed commitments
- commitments changed since the last review

Review format:
- structured data summary
- natural language summary

Reviews are surfaced as:
- Signal message (primary channel)
- Obsidian weekly note (stored in a configurable folder; default `_brain/commitments`)

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

---

## 13. Alignment with Brain Manifesto

- **Everything Compounds:** closed loops create leverage
- **Attention Is Sacred:** prompts are intentional
- **Truth Is Explicit:** commitments don’t vanish silently
- **Memory Is Curated:** patterns, not raw tasks, become memory

---

_End of PRD_
