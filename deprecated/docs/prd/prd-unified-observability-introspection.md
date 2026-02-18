# PRD: Unified Observability, Traceability & Introspection
## Seeing, Explaining, and Debugging Agent Behavior in Brain

---

## 1. Overview

### Feature Name
**Unified Observability & Introspection**

### Summary
Extend Brain with a **first-class observability layer** that makes the system *explainable after the fact*.

When something goes wrong — technically, logically, or behaviorally — the system must be able to answer, with evidence:

- What did the agent see?
- What did it decide?
- What tools did it call?
- What did it change?
- Why did it act that way?
- What else was happening at the same time?

This feature turns Brain from a black box into a **forensic, debuggable system**.

---

## 2. Problem Statement

As Brain gains:
- autonomy
- scheduling
- skills
- memory
- self-modification

failures become harder to diagnose.

Without structured observability:
- logs are fragmented
- causality is unclear
- reasoning is lost
- trust erodes quickly
- “why did it do that?” becomes unanswerable

Brain must support **post‑hoc explanation**, not just real‑time logging.

---

## 3. Goals and Non‑Goals

### Goals
- Provide end‑to‑end traceability of agent actions
- Correlate reasoning, tools, memory, and side effects
- Support both human inspection and programmatic analysis
- Make failures explainable without re‑running the agent
- Preserve privacy and safety boundaries

### Non‑Goals
- Perfect replay of internal model activations
- Storing full token‑level chain‑of‑thought
- Real‑time performance monitoring dashboards (initially)
- External SaaS observability dependencies

---

## 4. Design Principles

1. **Observability is a first‑class feature**
2. **Every side effect must have a cause**
3. **Correlation beats verbosity**
4. **Explanations must be reconstructable**
5. **Humans must be able to answer “why”**

---

## 5. Core Concepts

### 5.1 Trace
A **trace** represents a single unit of agent activity:
- user request
- scheduled execution
- watcher trigger
- self‑modification attempt

Each trace has a globally unique `trace_id`.

---

### 5.2 Span
A trace is composed of **spans**, representing:
- reasoning steps
- tool calls
- policy evaluations
- skill executions
- side effects

Spans are ordered and timestamped.

---

### 5.3 Context Snapshot
A snapshot of **relevant system context** captured at key points:
- active commitments
- relevant memory references
- policies in effect
- attention state
- actor identity

---

## 6. Functional Requirements

### 6.1 Trace Lifecycle

For every agent invocation:
- generate a `trace_id`
- propagate it across all components
- attach it to:
  - tool calls
  - database writes
  - messages
  - scheduled executions

No trace → no side effect.

---

### 6.2 Reasoning Introspection (Safe)

The system must capture:
- goals / intent summary
- constraints considered
- alternatives rejected (optional)
- uncertainty markers

This is a **structured explanation**, not raw chain‑of‑thought.

---

### 6.3 Tool & Skill Observability

For each tool or skill call, record:
- tool name + version
- input (redacted if needed)
- output / result
- success or failure
- duration
- side effects performed

---

### 6.4 Change Tracking

Any state mutation must be recorded:
- Obsidian writes (path + diff summary)
- Object store writes
- schedule changes
- commitment state transitions
- memory promotion proposals
- self‑modification attempts

All linked to the originating trace.

---

### 6.5 Temporal Correlation

The system must support answering:
> “What else was happening around this time?”

By querying:
- overlapping traces
- concurrent scheduled jobs
- recent policy changes
- recent memory promotions
- recent self‑modifications

---

## 7. Query & Inspection Interfaces

### 7.1 Programmatic API
- fetch trace by ID
- list traces by time window
- filter by:
  - actor
  - component
  - failure type
  - affected resource

### 7.2 Human‑Readable Views
- trace summary (timeline)
- “why did this happen?” explanation
- diff views for state changes

Optional:
- Obsidian‑rendered incident reports

---

## 8. Failure Classification

Each trace may be labeled as:
- technical (exception, crash, timeout)
- logical (bad decision, wrong outcome)
- behavioral (violated expectation or policy)

Classification may be automatic or human‑assigned.

---

## 9. Policy & Privacy Considerations

- Observability data is Tier 1 (durable but reconstructable)
- Sensitive inputs must be redacted or hashed
- No secrets or credentials stored
- Human inspection access is gated

---

## 10. Retention & Storage

- Raw traces retained for configurable period
- Summaries retained longer
- Aggregates may be kept indefinitely

Storage strategy must not impair system performance.

---

## 11. Risks and Mitigations

### Risk: Log Explosion
Mitigation:
- structured spans
- sampling
- configurable verbosity

### Risk: False Sense of Understanding
Mitigation:
- explicit uncertainty markers
- avoid fabricated explanations

---

## 12. Success Metrics

- Ability to explain failures post‑hoc
- Reduced time to diagnose issues
- Increased user trust
- Fewer “mystery behaviors”
- Clear audit trail of all side effects

---

## 13. Definition of Done

- [ ] Trace + span model implemented
- [ ] Context snapshots captured
- [ ] Tool, skill, and change logging unified
- [ ] Query APIs available
- [ ] Human‑readable explanations generated
- [ ] Policy and privacy enforced

---

## 14. Alignment with Brain Manifesto

- **Truth Is Explicit:** actions explain themselves
- **Actions Are Bounded:** side effects are traceable
- **Sovereignty First:** observability is local and inspectable
- **Everything Compounds:** understanding failures improves future behavior

---

_End of PRD_
