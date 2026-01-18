# PRD: Skill Framework (Logic, Pipeline, and Ops)
## Governed Capability Composition for Brain

---

## 1. Overview

### Feature Name
**Skill Framework v2 (Logic / Pipeline / Ops)**

### Summary
Define a unified skill framework where all agent capabilities are expressed as:

- **Logic skills** (custom orchestration with declared call graph)
- **Pipeline skills** (declarative composition)
- **Ops** (atomic execution units, native or MCP-backed)

This framework enforces:
- explicit capability boundaries
- static call-graph validation
- type-safe composition
- uniform policy and observability

Prerequisite understanding: skills-glossary.md.

---

## 2. Problem Statement

As Brain grows:
- capabilities multiply
- tools span native and MCP planes
- autonomy increases

Without a strict framework:
- dependencies become implicit
- policies are bypassed accidentally
- observability fragments
- safety degrades

The system requires a **single execution grammar**.

---

## 3. Goals and Non-Goals

### Goals
- Canonicalize Skill and Op terminology
- Support both declarative and code-based skills
- Treat MCP and native functionality uniformly
- Enable static validation of composition
- Enable runtime validation of call graphs against expectations

### Non-Goals
- Turing-complete declarative languages
- Implicit tool invocation
- Unbounded agent autonomy
- Runtime inference of dependencies

---

## 4. Core Model

```
Op (atomic)
   ↑
Skill (pipeline or logic)
   ↑
Agent
```

All execution flows through this hierarchy.

---

## 5. Validation & Type Safety

### 5.1 Static Validation

The system must validate:
- pipeline step wiring
- input/output schema compatibility
- capability closure
- autonomy level escalation

---

### 5.2 Runtime Enforcement

At runtime:
- undeclared calls error immediately
- policy gates are enforced per call
- traces record the full call tree

---

## 6. Governance & Autonomy

- Skills declare required capabilities
- Pipeline skills inherit the union of step capabilities
- Logic skills must explicitly whitelist call targets
- Lower-autonomy call targets still enforce their own approval requirements

---

## 7. Observability

Each invocation produces:
- a trace
- spans for each skill/op call
- inputs/outputs (with redaction)
- policy decisions

The system must answer:
> “What was called, by whom, and why?”

---

## 8. Success Metrics

- Zero implicit dependencies
- Predictable, inspectable behavior
- Reduced boilerplate for simple capabilities
- Safe composition at scale

---

## 9. Definition of Done

- [X] Canonical glossary published
- [ ] Skill registry supports logic/pipeline kinds
- [ ] Ops unified across native and MCP
- [ ] Static validator implemented
- [ ] Runtime call-graph enforcement active
- [ ] Observability integrated

---

_End of PRD_
