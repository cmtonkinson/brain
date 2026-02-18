# PRD: Skill Framework & Capability Registry
## Bounded, Testable, and Composable Capabilities for Brain

---

## 1. Overview

### Feature Name
**Skill Framework & Capability Registry**

### Summary
Introduce a **Skill Framework** that defines reusable, bounded, and testable capabilities (“skills”) for Brain, along with a **Capability Registry** that governs how those skills are discovered, invoked, authorized, and evolved over time.

This feature ensures Brain scales via **composable skills**, not ad‑hoc prompts or bespoke automation, enabling leverage, safety, and long‑term maintainability.

---

## 2. Problem Statement

Without a skill abstraction, agent systems tend to:
- re‑solve the same problems repeatedly
- encode logic implicitly in prompts
- blur boundaries between reasoning and execution
- accumulate fragile, untestable behavior
- become difficult to audit or evolve

Brain requires a **first‑class abstraction for “what it knows how to do.”**

---

## 3. Goals and Non‑Goals

### Goals
- Define a clear abstraction for skills
- Make skills reusable and composable
- Enforce bounded authority and policy per skill
- Enable testing and inspection of skills
- Decouple skills from specific UI or trigger mechanisms

### Non‑Goals
- A plugin marketplace
- End‑user visual programming (initially)
- Autonomous skill creation without review
- Encoding entire workflows as single skills

---

## 4. Design Principles

1. **Skills are capabilities, not conversations**
2. **Every skill has a contract**
3. **Authority is explicit and bounded**
4. **Skills must be testable in isolation**
5. **Skills compound over time**

---

## 5. Core Concepts

### 5.1 Skill
A skill is a **named, reusable capability** that:
- accepts structured input
- performs bounded work
- may call tools or other skills
- produces structured output and/or side effects

Examples:
- “Clip URL and summarize”
- “Prepare meeting brief”
- “Create reminder from text”
- “Weekly review”

---

### 5.2 Capability
A capability represents **what the system is allowed to do**, independent of implementation.

Examples:
- calendar.read
- calendar.write
- messaging.send
- memory.propose
- blob.store

Skills declare which capabilities they require.

---

### 5.3 Registry
The Capability Registry is the authoritative inventory of:
- available skills
- their contracts
- required capabilities
- policy constraints
- versions and status

---

## 6. Skill Contract

Every skill must declare:

- name
- description (human‑readable)
- input schema
- output schema
- side effects
- required capabilities
- autonomy level
- failure modes (structured error codes)

Example (conceptual):

```json
{
  "name": "clip_and_summarize_url",
  "inputs": { "url": "string" },
  "outputs": { "summary": "string", "note_path": "string" },
  "capabilities": ["blob.store", "obsidian.write"],
  "autonomy": "L1"
}
```

---

## 7. Functional Requirements

### 7.1 Skill Invocation

Skills may be invoked by:
- agent reasoning
- scheduled tasks
- user requests
- other skills

Invocation always passes through:
- policy checks
- capability authorization
- attention routing (if user‑visible)

---

### 7.2 Skill Composition

Skills may:
- call other skills
- share intermediate artifacts
- build higher‑order workflows

Composition must preserve:
- capability boundaries
- auditability
- failure isolation

---

### 7.3 Capability Enforcement

Before execution:
- required capabilities are validated
- context‑specific restrictions applied
- missing capabilities cause explicit failure

No implicit privilege escalation is allowed.

---

### 7.4 Versioning & Evolution

Skills must support:
- explicit versions
- deprecation
- migration paths

Breaking changes require:
- new version
- explicit opt‑in

---

## 8. Registry Responsibilities

The Capability Registry must:
- list all available skills
- expose metadata to the agent
- support enable/disable per environment
- support allow/deny per channel or actor
- record usage statistics (optional)

---

## 9. Testing & Validation

Each skill must be:
- unit‑testable without the agent
- testable with mocked tools
- validated against its schema

Skills are the **unit of reliability**.

---

## 10. Observability & Audit

For each skill execution:
- inputs (redacted as needed)
- outputs
- side effects
- duration
- success/failure
- invoking actor

This enables:
- debugging
- performance tuning
- trust building

---

## 11. Risks and Mitigations

### Risk: Skill Explosion
Mitigation:
- prefer composition over proliferation
- periodic skill reviews
- deprecate unused skills

### Risk: Overpowered Skills
Mitigation:
- fine‑grained capabilities
- conservative autonomy defaults
- policy enforcement

---

## 12. Success Metrics

- Reduced duplicated logic
- Increased reuse of capabilities
- Faster feature development
- Clear audit trail of agent actions
- Higher trust in automation

---

## 13. Definition of Done

- [ ] Skill abstraction defined
- [ ] Capability registry implemented
- [ ] Policy enforcement per skill
- [ ] Skill composition supported
- [ ] Testing framework in place
- [ ] Observability implemented

---

## 14. Alignment with Brain Manifesto

- **Everything Compounds:** skills create leverage
- **Actions Are Bounded:** capabilities constrain power
- **Truth Is Explicit:** contracts define behavior
- **Sovereignty First:** skills are local and inspectable

---

_End of PRD_
