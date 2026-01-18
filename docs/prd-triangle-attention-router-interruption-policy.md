# PRD: Attention Router & Interruption Policy
## Intelligent Notification, Escalation, and Silence for Brain OS

---

## 1. Overview

### Feature Name
**Attention Router & Interruption Policy**

### Summary
Introduce a centralized **Attention Router** responsible for deciding **if, when, how, and how much** Brain OS communicates with the human.

This feature enforces the principle *Attention Is Sacred* by ensuring that:
- interruptions are intentional
- notifications are proportional
- silence is often the correct outcome
- all outbound communication respects context, urgency, and trust

The Attention Router becomes the **mandatory gate** for all agent-initiated outbound communication.

---

## 2. Problem Statement

Without a unified attention policy, intelligent systems tend to:
- over-notify
- escalate too early
- duplicate information across channels
- interrupt at poor times
- erode trust through noise

Brain OS must operate in an environment of **scarce human attention**.  
The system’s value depends as much on *what it withholds* as on what it delivers.

---

## 3. Goals and Non-Goals

### Goals
- Centralize all outbound communication decisions
- Reduce notification volume without losing important signals
- Support multiple channels with clear roles
- Respect time, focus, and context
- Enable explainable notification decisions

### Non-Goals
- Replacing operating system notification systems
- Predicting emotional state with high confidence
- Real-time behavioral monitoring
- Guaranteeing zero interruptions

---

## 4. Design Principles

1. **Silence is a valid outcome**
2. **Urgency must be earned**
3. **Channels have intent, not equality**
4. **Interruptions should close loops**
5. **Humans must understand why they were interrupted**

---

## 5. Core Concepts

### 5.1 Signal
A piece of information the system *could* communicate.

Examples:
- task completed
- task failed
- new information detected
- clarification required
- review available

---

### 5.2 Interruption
A decision to surface a signal to the human.

Interruption is optional and policy-driven.

---

### 5.3 Channel
A delivery medium with implicit cost and semantics.

Typical channels:
- Signal (high urgency, conversational)
- Obsidian note (low urgency, durable)
- Web UI (pull-based, exploratory)
- Digest (batched, scheduled)

Channels are not interchangeable.

---

### 5.4 Attention Context
The system’s model of *when and how interruptible* the human is.

Inputs may include:
- time of day
- calendar state
- quiet hours
- recent interruptions
- explicit user preferences

---

## 6. Functional Requirements

### 6.1 Mandatory Routing

All outbound communication initiated by:
- scheduled tasks
- watchers
- skills
- memory governance
- agent reasoning

**must pass through the Attention Router**.

No component may bypass this layer.

If the router or its policy engine is unavailable, it must **fail closed**:
- default to `LOG_ONLY`
- queue signals for later review/delivery
- avoid direct notification

---

### 6.2 Interruption Decision

For each signal, the router must decide:
- suppress
- defer
- batch
- notify immediately

Decision inputs:
- signal urgency
- confidence
- human attention context
- channel cost
- recent notification history

---

### 6.3 Channel Selection

If notifying, the router selects:
- primary channel
- optional secondary record (e.g. Obsidian log)

Examples:
- urgent failure → Signal
- routine update → digest
- long-form analysis → Obsidian
- exploration → Web UI only

---

### 6.4 Escalation Policy

Signals may escalate if:
- ignored repeatedly
- approaching deadline
- increasing severity

Escalation is gradual and explicit.

---

### 6.5 Batching & Digests

The system must support:
- daily digests
- weekly reviews
- topic-based batching

Batched signals are summarized and ranked.

---

### 6.6 Notification Envelope (Provenance & Confidence)

All notifications must include a wrapper with:
- source component
- provenance (originating signal + inputs)
- confidence level

This metadata is surfaced to the human in a compact form and logged for audit.

---

## 7. Interruption Policy Model

### 7.1 Policy Inputs

Policies may reference:
- signal type
- source component
- urgency level
- confidence score
- user-defined preferences
- time windows

---

### 7.2 Policy Outcomes

Possible outcomes:
- `DROP`
- `LOG_ONLY`
- `DEFER`
- `BATCH`
- `NOTIFY(channel)`
- `ESCALATE(channel)`

Outcomes must be explainable.

---

## 8. Human Preferences & Overrides

Users may define:
- quiet hours
- do-not-disturb windows
- channel preferences
- escalation thresholds
- “always notify” exceptions

Overrides are explicit and auditable.

---

## 9. Observability & Audit

The system must log:
- all signals generated
- routing decisions
- policies applied
- notifications sent or suppressed

Optional:
- “Why did I get this?” explanation surfaced to user
- periodic attention usage summaries

---

## 10. Risks and Mitigations

### Risk: Over-Suppression
Mitigation:
- periodic reviews of suppressed signals
- escalation paths for unresolved signals

### Risk: Notification Spam
Mitigation:
- rate limits
- batching
- channel cost weighting

---

## 11. Success Metrics

- Reduced notification volume
- High perceived signal-to-noise ratio
- Fewer ignored or dismissed alerts
- Increased trust in system communications
- Clear rationale for interruptions

---

## 12. Definition of Done

- [ ] Attention Router implemented as mandatory gate
- [ ] Policy model defined and enforced
- [ ] Channel selection logic implemented
- [ ] Batching and digest support
- [ ] Audit logging in place
- [ ] Human preference configuration available

---

## 13. Alignment with Brain OS Manifesto

- **Attention Is Sacred:** silence and batching are first-class
- **Actions Are Bounded:** interruptions are deliberate
- **Truth Is Explicit:** routing decisions are explainable
- **Everything Compounds:** better attention management improves long-term trust

---

_End of PRD_
