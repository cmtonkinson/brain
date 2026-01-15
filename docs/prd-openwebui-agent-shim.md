# PRD: OpenWebUI Integration via OpenAI-Compatible Shim
## Web Interface Layer for Brain OS

---

## 1. Overview

### Feature Name
**OpenWebUI Integration (Agent-Backed)**

### Summary
Provide a **web-based user interface** for Brain OS by integrating **OpenWebUI** on top of the agent runtime through a **lightweight OpenAI-compatible HTTP shim**.

This allows users to interact with the full Brain OS agent (memory, tools, policies, scheduling) via a modern web UI, without exposing internal implementation details or duplicating agent logic.

---

## 2. Problem Statement

Brain OS currently exposes interaction primarily via:
- Messaging interfaces (Signal)
- Direct API calls / developer tooling

While powerful, these interfaces are:
- inconvenient for exploratory or long-form interaction
- difficult to use for debugging, inspection, and iteration
- unfriendly for ad-hoc reasoning, review, or planning sessions

Users need a **low-friction, visual interface** that:
- does not bypass the agent
- does not create a second “brain”
- does not weaken policy or safety boundaries

---

## 3. Goals and Non-Goals

### Goals
- Provide a full-featured web UI for Brain OS
- Reuse an existing, high-quality UI (OpenWebUI)
- Preserve Brain OS as the sole agent of record
- Avoid duplicating tool orchestration or memory logic
- Maintain strict separation between UI and agent internals

### Non-Goals
- Replacing Signal as the primary low-noise interface
- Exposing raw MCP tools directly to the UI
- Allowing UI-driven configuration of models, prompts, or tools
- Supporting multiple competing agent runtimes

---

## 4. Design Principles

1. **UI is a façade, not a brain**
2. **The agent owns reasoning, tools, and memory**
3. **All requests flow through the same policy gates**
4. **OpenAI compatibility is a protocol choice, not a dependency**
5. **One agent, many interfaces**

---

## 5. High-Level Architecture

```
OpenWebUI
   ↓ (OpenAI-compatible HTTP)
OpenAI Shim (brain-api)
   ↓
PydanticAI Agent (Brain)
   ↓
LiteLLM → Models
   ↓
MCP Tools / Schedulers / Memory
```

---

## 6. Functional Requirements

### 6.1 OpenAI-Compatible Endpoint

The shim must implement a subset of the OpenAI API sufficient for OpenWebUI:

- `POST /v1/chat/completions`
- Support for:
  - messages array
  - system / user / assistant roles
  - streaming (optional but recommended)

The shim **must not** expose:
- model selection
- temperature or sampling controls
- tool schemas
- system prompt injection

---

### 6.2 Agent Invocation

For each incoming request:
- Extract user intent from messages
- Invoke the Brain OS agent runtime
- Allow the agent to:
  - access memory (Letta)
  - call MCP tools
  - schedule work
  - propose or execute actions
- Return the agent’s final response to OpenWebUI

---

## 7. Security and Policy

### Policy Enforcement

All requests from OpenWebUI:
- are treated as **interactive, high-context sessions**
- pass through the same policy engine as other interfaces
- are subject to:
  - tool allowlists
  - read/write separation
  - confirmation requirements

---

## 8. Observability

The system must log:
- inbound UI requests
- agent decisions
- tool invocations
- response latency
- errors and policy denials

---

## 9. UX Considerations

### Intended Use Cases
- exploratory reasoning
- reviewing plans or summaries
- debugging agent behavior
- long-form writing or planning

### Explicitly Not Optimized For
- notifications
- alerts
- background execution

---

## 10. Success Metrics

- OpenWebUI can fully interact with Brain OS
- No divergence between UI and Signal behavior
- Reduced friction for debugging and exploration
- No increase in unsafe actions

---

## 11. Definition of Done

- OpenWebUI successfully connects to brain-api
- OpenAI-compatible shim implemented
- Agent responses visible in UI
- Policy enforcement verified
- Logging enabled

---

_End of PRD_
