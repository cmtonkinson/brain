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
- description
- provenance (who/what created it)
- due time or trigger
- related artifacts (notes, messages)

---

### 6.2 Tracking & State Management

The system must:
- track current state
- record state transitions
- timestamp all changes
- associate outcomes with actions taken

---

### 6.3 Miss Detection

If a commitment passes its due time without closure:
- mark as `MISSED`
- record context (what happened)
- route signal via Attention Router (policy-controlled)

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

## 8. Observability & Audit

For each commitment, store:
- creation source
- full lifecycle history
- resolution notes (optional)
- related notifications

Optional:
- Obsidian “Commitment Log” notes
- Weekly summaries of open vs closed loops

---

## 9. Review & Reflection

### 9.1 Periodic Reviews

Support scheduled reviews (weekly/monthly):
- open commitments
- missed commitments
- renegotiated commitments
- patterns (overcommitment, delays)

Reviews are surfaced as:
- Obsidian notes
- optional conversational prompts

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
