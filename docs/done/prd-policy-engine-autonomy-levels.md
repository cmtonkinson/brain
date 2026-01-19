# PRD: Policy Engine & Autonomy Levels
## Governing Authority, Risk, and Action in Brain

---

## 1. Overview

### Feature Name
**Policy Engine & Autonomy Levels**

### Summary
Introduce a centralized **Policy Engine** that governs *what Brain is allowed to do*, *under which conditions*, and *with what level of autonomy*.

This feature formalizes:
- authority boundaries
- risk management
- approval requirements
- escalation rules

It ensures Brain remains **powerful but predictable**, capable of action without ever becoming unsafe, surprising, or untrustworthy.

---

## 2. Problem Statement

As Brain gains capabilities (skills, scheduling, messaging, memory, automation), risk grows non-linearly.

Without a formal policy layer:
- autonomy becomes implicit and inconsistent
- dangerous actions slip through convenience paths
- different interfaces behave differently
- users lose confidence in what the system *might* do

Brain requires a **single source of truth for authority and autonomy**.

---

## 3. Goals and Non-Goals

### Goals
- Define explicit autonomy levels for all actions
- Centralize permission checks across the system
- Enforce human-in-the-loop controls
- Enable explainable “why was this allowed/blocked?”
- Support gradual increases in autonomy over time

### Non-Goals
- Moral reasoning or ethical judgment
- Fully autonomous agent behavior
- Hard-coded safety logic scattered across services
- Replacing human responsibility for decisions

---

## 4. Design Principles

1. **Power must be earned**
2. **Nothing acts without authority**
3. **Defaults are conservative**
4. **Policies are explicit, inspectable, and auditable**
5. **Autonomy is contextual, not absolute**

---

## 5. Core Concepts

### 5.1 Policy
A policy is a rule that determines:
- whether an action is allowed
- under what conditions
- with what level of approval

Policies are data, not code. Current implementation evaluates policy in
code using registry metadata and overlays; the policy data lives in those
registries and overlay files, while the evaluator logic remains centralized.

---

### 5.2 Action
An action is any operation that causes side effects. In the current
framework, policy evaluation is applied at **skill** and **op**
invocation boundaries (including pipeline steps).

Examples:
- sending a message
- creating a calendar event
- promoting memory
- deleting data
- scheduling future work

---

### 5.3 Actor
The entity requesting an action.

Examples:
- user (interactive)
- scheduled job
- watcher
- skill
- system maintenance

---

### 5.4 Autonomy Level
Defines how freely an action may execute.

Autonomy is evaluated **per action, per context**.

---

## 6. Autonomy Levels (Canonical)

### L0 — Suggest Only
- Action may be proposed
- No execution
- Human must explicitly initiate

Examples:
- proposing memory
- suggesting a task
- drafting content

---

### L1 — Draft + Approval
- System prepares a draft
- Explicit approval required before execution

Examples:
- sending email
- creating calendar events
- promoting memory

---

### L2 — Bounded Automatic
- Action executes automatically
- Fully reversible
- Low risk

Examples:
- tagging notes
- updating internal metadata
- marking tasks complete

---

### L3 — Automatic with Guardrails
- Executes automatically
- Bounded scope
- Audited and monitored

Examples:
- recurring summaries
- daily brief generation
- watcher polling

---

### L4 — Restricted Autonomy (Future)
- High trust, rare usage
- Explicit opt-in
- Continuous audit

Not enabled by default. (Current implementation supports L0-L3 only.)

---

## 7. Functional Requirements

### 7.1 Policy Evaluation

Before any action:
- identify actor
- identify action type
- identify required capabilities
- evaluate applicable policies
- determine required autonomy level

Action proceeds only if policy permits.

---

### 7.2 Approval Workflow

For actions requiring approval (planned workflow):
- generate a proposal artifact
- route via Attention Router
- wait for explicit confirmation
- execute or cancel based on response

Approvals are time-bound and logged.

Current implementation uses a `confirmed` flag on the execution context
to gate L1 and `requires_review` policy tags.

---

### 7.3 Capability Binding

Policies bind:
- actions → required capabilities
- capabilities → allowed autonomy levels
- actors → maximum autonomy

This prevents privilege escalation.

In the current skill framework, allowed capabilities are carried on the
execution context and narrowed on child calls (including pipeline steps),
so child invocations cannot expand their capability set.

---

### 7.4 Context Sensitivity

Policy decisions may consider:
- time of day
- channel (Signal)
- recent failures
- confidence levels
- historical trust

---

## 8. Policy Definition Model

Policies should be defined in a structured format, e.g.:

```yaml
action: messaging.send
actor: scheduled
max_autonomy: L1
requires_approval: true
conditions:
  - quiet_hours: false
```

Policies are versioned and reloadable at runtime.

Current implementation evaluates policy in code using registry metadata
and overlays (autonomy overrides, channels/actors allow/deny, rate limits,
and policy tags). A structured policy file is a planned extension.

---

## 9. Observability & Audit

For every evaluated action, log:
- actor
- action
- policy applied
- autonomy level
- outcome (allowed, blocked, approved)

Optional:
- human-readable explanations
- policy decision traces

---

## 10. Risks and Mitigations

### Risk: Policy Complexity
Mitigation:
- small, composable rules
- clear defaults
- periodic policy reviews

### Risk: Over-Restriction
Mitigation:
- graduated autonomy
- explicit overrides
- dry-run evaluation tools

---

## 11. Success Metrics

- No unauthorized actions executed
- Clear understanding of agent authority
- Reduced user anxiety about automation
- Safe increase in autonomy over time
- Consistent behavior across interfaces

---

## 12. Definition of Done

- [ ] Autonomy levels formally defined
- [ ] Policy schema implemented
- [ ] Policy evaluation enforced system-wide
- [ ] Approval workflow integrated
- [ ] Audit logging in place
- [ ] Human-readable policy documentation

---

## 13. Alignment with Brain Manifesto

- **Actions Are Bounded:** autonomy is explicit
- **Truth Is Explicit:** policy decisions are explainable
- **Attention Is Sacred:** approvals are intentional
- **Sovereignty First:** authority remains human-centered

---

_End of PRD_
