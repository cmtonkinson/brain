# PRD: Sequential Thinking MCP Server
## Structured, Inspectable Multi‑Step Reasoning for Brain

---

## 1. Overview

### Feature Name
**Sequential Thinking MCP Server**

### Summary
Introduce a **Sequential Thinking MCP Server** that provides Brain with a structured, stepwise reasoning capability, allowing the agent to explicitly plan, track, revise, and evaluate multi-step thinking processes **without exposing raw chain-of-thought**.

This server enables:
- deliberate reasoning over complex problems
- inspectable intermediate steps
- safe introspection for debugging and governance
- separation of *reasoning structure* from *model internals*

Sequential Thinking becomes a **first-class cognitive tool**, not an implicit side effect of prompting.

---

## 2. Problem Statement

As Brain handles:
- multi-step workflows
- long-running plans
- policy-constrained decisions
- self-modification and recovery
- observability and governance

implicit, monolithic reasoning becomes:
- opaque
- hard to debug
- difficult to audit
- impossible to resume or revise

Brain needs a way to **reason in stages**, with memory, revision, and accountability — without violating safety constraints around chain-of-thought exposure.

---

## 3. Goals and Non-Goals

### Goals
- Enable structured, step-by-step reasoning
- Allow revision and backtracking of reasoning steps
- Persist reasoning artifacts for inspection
- Integrate with observability and policy systems
- Support resumable and interruptible reasoning

### Non-Goals
- Exposing raw LLM chain-of-thought
- Guaranteeing logical correctness
- Replacing core agent reasoning
- Autonomous self-justification without evidence

---

## 4. Design Principles

1. **Structure over verbosity**
2. **Reasoning is an artifact**
3. **Steps are inspectable, not sacred**
4. **Revision is expected**
5. **Safety over introspective purity**

---

## 5. Core Concepts

### 5.1 Thought Step
A single unit of reasoning representing:
- a hypothesis
- a decision
- an evaluation
- a plan element

Each step is **explicit, labeled, and typed**.

---

### 5.2 Thought Chain
An ordered collection of thought steps with:
- parent/child relationships
- revisions and replacements
- branching (optional)

A thought chain is **stateful and resumable**.

---

### 5.3 Reasoning Session
A bounded context in which sequential thinking occurs.

Examples:
- planning a complex task
- debugging a failure
- evaluating policy compliance
- proposing a self-modification

---

## 6. Functional Requirements

### 6.1 MCP Tool Interface

Expose the following MCP operations:

- `start_reasoning_session`
- `add_thought_step`
- `revise_thought_step`
- `discard_thought_step`
- `evaluate_chain`
- `finalize_reasoning`

Each operation must:
- accept structured input
- return identifiers for traceability
- be idempotent where possible

---

### 6.2 Thought Step Schema

Each step must include:
- step_id
- type (plan, assumption, evaluation, decision, risk, etc.)
- content (concise, human-readable)
- confidence (optional)
- references (links to traces, notes, artifacts)
- timestamp

No raw chain-of-thought tokens are stored.

---

### 6.3 Persistence

The server must persist:
- reasoning sessions
- thought steps and revisions
- final conclusions

Persistence is **Tier 1 data** (durable, reconstructable).

---

### 6.4 Integration with Agent

The agent may:
- invoke sequential thinking explicitly for complex tasks
- pause and resume sessions
- reference finalized reasoning in later decisions
- surface summaries to humans

Sequential thinking is **opt-in**, not mandatory.

---

## 7. Policy & Autonomy

- Starting a reasoning session: L2
- Persisting reasoning artifacts: allowed
- Using reasoning to justify actions: required for high-risk actions
- Modifying policies or self-code requires:
  - completed reasoning session
  - explicit final evaluation step

Sequential thinking strengthens, not bypasses, policy.

---

## 8. Observability & Audit

Each reasoning session must be linked to:
- initiating trace_id
- invoking actor
- downstream actions taken
- outcomes (success, failure, rollback)

The system must answer:
> “What reasoning led to this action?”

---

## 9. Safety & Privacy

- Reasoning content must avoid sensitive data
- Steps may be redacted or summarized
- Sessions may be marked private or shared
- No automatic exposure to external UIs

---

## 10. Failure Modes & Recovery

### Interrupted Session
- Session can be resumed
- Partial steps remain visible

### Contradictory Steps
- Conflicts are explicit
- Revision is preferred to deletion

### Abandoned Session
- Marked stale
- Excluded from future justification

---

## 11. Use Cases

- Debugging a failed scheduled task
- Planning a multi-stage ingestion workflow
- Evaluating whether to self-modify
- Explaining why an action was taken
- Post-mortem analysis

---

## 12. Success Metrics

- Clear, inspectable reasoning trails
- Reduced debugging time
- Improved trust in agent decisions
- Fewer unexplained actions
- Safe handling of complex autonomy

---

## 13. Definition of Done

- [ ] MCP server implemented
- [ ] Thought step schema defined
- [ ] Reasoning sessions persisted
- [ ] Agent integration complete
- [ ] Policy hooks enforced
- [ ] Observability links in place

---

## 14. Alignment with Brain Manifesto

- **Truth Is Explicit:** reasoning is visible
- **Actions Are Bounded:** decisions are justified
- **Everything Compounds:** reasoning artifacts improve future behavior
- **Sovereignty First:** introspection is local and controlled

---

_End of PRD_
