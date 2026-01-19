# PRD: Scheduled & Timed Task Execution
## Dynamic, Policy-Aware Scheduling for Brain

---

## 1. Overview

### Feature Name
**Scheduled & Timed Tasks**

### Summary
Introduce a **flexible, dynamic scheduling system** that allows Brain to execute tasks at specific times, on recurring schedules, or in response to temporal conditions — without hard-coding schedules into the system or binding the design to any specific task framework or queueing technology.

This feature enables Brain to:
- wake up on its own
- execute deferred intentions
- run periodic reviews and watchers
- deliver notifications and follow-ups at the right time

All while respecting autonomy, policy, and attention constraints.

---

## 2. Problem Statement

Brain currently excels at *reactive* behavior — responding to user input and external triggers — but lacks a first-class abstraction for **time**.

Without a scheduling layer:
- reminders are brittle or ad hoc
- follow-ups lose context
- long-running intentions cannot be reliably expressed
- automation becomes either static (cron files) or overly complex

Brain requires a **time-aware execution model** that is:
- dynamic
- inspectable
- policy-governed
- decoupled from implementation details

---

## 3. Goals and Non-Goals

### Goals
- Support one-off, recurring, and conditional timed tasks
- Allow schedules to be created, modified, paused, or canceled at runtime
- Enable scheduled tasks to invoke the Brain agent safely
- Persist task intent and state durably
- Integrate with memory, attention, and policy layers

### Non-Goals
- Real-time sub-second task execution
- Hard dependency on any specific scheduler, queue, or framework
- User-facing calendar replacement
- Fully autonomous background actions without policy review

---

## 4. Design Principles

1. **Time is a first-class input**
2. **Schedules are data, not configuration**
3. **Execution is decoupled from intent**
4. **All scheduled actions are policy-bound**
5. **Humans must be able to inspect and reason about schedules**

---

## 5. Core Concepts

### 5.1 Task Intent
Represents *why* something should happen.

Examples:
- “Remind me to follow up”
- “Send me a daily brief”
- “Check this page for updates”
- “Review memory hygiene weekly”

Task intent is immutable and human-readable.

---

### 5.2 Schedule
Defines *when* execution should occur.

Supported schedule types:
- one-time (at timestamp)
- interval-based (every N minutes/hours/days)
- calendar-based (cron-like expressions)
- conditional (run when predicate becomes true)

Schedules must be editable at runtime.

---

### 5.3 Execution
Represents *what actually runs* at a given time.

Execution:
- invokes Brain with a specific actor context
- may succeed, fail, retry, or defer
- produces observable side effects (notifications, notes, actions)

Execution is ephemeral; intent and schedule are durable.

---

## 6. Functional Requirements

### 6.1 Schedule Management API

The system must support:
- create schedule
- update schedule
- pause/resume schedule
- delete schedule
- trigger immediately (“run now”)

Schedules are identified by stable IDs.

---

### 6.2 Execution Invocation

At execution time:
- the scheduler triggers a task execution
- execution calls the Brain agent via its public API
- agent receives:
  - task intent
  - actor context (scheduled job)
  - execution metadata (time, retries, history)

The agent decides how to act.

---

### 6.3 Retry & Failure Semantics

The system must support:
- configurable retries
- backoff strategies
- permanent failure states
- human notification on repeated failure

Failures must never be silent.

---

### 6.4 State & History

The system must persist:
- task intent
- schedule definition
- last execution time
- last execution result
- failure count

This enables audit, debugging, and trust.

---

## 7. Policy & Safety Integration

### 7.1 Actor Context

Scheduled tasks run as a distinct actor:
- channel: `scheduled`
- privilege level: constrained
- autonomy level: limited

This prevents background tasks from exceeding authority.

---

### 7.2 Attention Routing

Scheduled executions must respect:
- quiet hours
- batching rules
- escalation thresholds

Not every scheduled task produces a notification.

---

### 7.3 Memory Interaction

Scheduled tasks:
- may propose memory
- may reference memory
- may never promote memory directly

Promotion authority remains with Letta.

---

## 8. Observability & Audit

For each task and execution, the system must record:
- creation time and creator
- schedule definition
- execution timestamps
- outcomes
- side effects

Optional:
- summarized execution logs in Obsidian
- dashboards or CLI inspection tools

---

## 9. Extensibility

The design must employ some sort of e.g. adapter pattern to decouple the specific scheduler implementation from core logic, separating scheduler technology choice from Brain design decisions. No Brain logic should depend on a specific scheduler library.

A selection of scheduler tooling should be made however, in line with the existing project structure and norms. For example, scheduler should likely exist inside of a new Docker container(s) and should likely be a "buy" decision: leveraging existing open source package/s.

---

## 10. Risks and Mitigations

### Risk: Orphaned or Forgotten Schedules
Mitigation:
- inspection APIs
- periodic “scheduled tasks review”

### Risk: Over-Automation
Mitigation:
- conservative default autonomy
- human-in-the-loop approvals
- explicit policy gates

---

## 11. Success Metrics

- Tasks run when expected
- Schedules can be modified without redeploys
- No silent failures
- Clear audit trail of all executions
- Increased follow-through on commitments

---

## 12. Definition of Done

- [ ] Schedule and task intent data model defined
- [ ] Runtime schedule management supported
- [ ] Execution invokes Brain agent
- [ ] Policy and attention routing enforced
- [ ] Execution history persisted
- [ ] Review and inspection mechanisms available

---

## 13. Alignment with Brain Manifesto

- **Attention Is Sacred:** scheduled actions respect interruption policies
- **Actions Are Bounded:** background work runs with limited authority
- **Truth Is Explicit:** task intent and outcomes are auditable
- **Everything Compounds:** scheduled reviews and follow-ups improve outcomes

---

_End of PRD_
