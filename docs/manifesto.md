# Brain OS
## A Manifesto and Architecture Doctrine for a Personal Cognitive Infrastructure

> This system is not an AI assistant.
> It is a private operating system for attention, memory, intent, and action.

---

## 1. Purpose (The Why)

Modern knowledge work suffers from a fundamental asymmetry:

- Capture is cheap; understanding is expensive.
- Planning is easy; execution is fragile.
- Memory is abundant; trust is scarce.
- Automation is powerful; autonomy is dangerous.

**Brain OS exists to restore balance.**

Its purpose is to:
- turn *attention* into durable knowledge,
- turn *knowledge* into bounded action,
- and do so in a way that is private, auditable, and trustworthy over time.

If this system works, it should feel less like “AI” and more like **calm, competent leverage**.

---

## 2. Core First Principles (Non-Negotiable)

### 2.1 Sovereignty First
All authoritative data must be owned, inspectable, and portable.

- Local-first by default
- No silent cloud dependencies
- No opaque state that cannot be audited

Convenience is allowed. Loss of sovereignty is not.

---

### 2.2 Truth Is Explicit
The system must distinguish between:

- **facts**
- **claims**
- **inferences**
- **summaries**
- **guesses**

Every durable artifact must carry:
- provenance (where it came from)
- confidence (how sure we are)
- reversibility (how easily it can be undone)

The system must never pretend certainty where none exists.

---

### 2.3 Attention Is Sacred
Interruptions are the most expensive resource.

The system must:
- batch when possible
- defer when appropriate
- escalate only when necessary
- respect time, focus, and context

Silence is a valid and often optimal outcome.

---

### 2.4 Memory Is Curated, Not Accumulated
Memory is not storage.

- Most things should be forgotten.
- Some things should be summarized.
- Very few things should be remembered permanently.

Durable memory must be:
- stable
- meaningful
- human-auditable
- intentionally promoted

---

### 2.5 Actions Are Bounded
The system may suggest freely.
It may draft cautiously.
It may act only within explicit, reviewable boundaries.

Autonomy is **earned**, contextual, and revocable.

---

### 2.6 Everything Must Compound
The system should get better over time, not just bigger.

- skills should be reusable
- knowledge should reduce future effort
- mistakes should feed learning
- repetition should create leverage

If something does not compound, it is suspect.

---

## 3. Architectural Doctrine

### 3.1 Layered Responsibility Model

The system is composed of layers with **clear authority boundaries**.

#### Tier 0 — Authoritative Truth (Must Be Backed Up)
- Obsidian vault (Markdown knowledge, promoted memory)
- Object storage (raw blobs: HTML, PDFs, audio, images)

These are the canonical sources of truth.

---

#### Tier 1 — Durable System State (Backed Up Pragmatically)
- Agent memory store (Letta, e.g. Postgres)
- Scheduler / job state
- Message linkage state (e.g. Signal CLI identity)

Loss is painful but survivable.

---

#### Tier 2 — Derived / Cache (Rebuildable)
- Vector indexes
- Embeddings
- Summaries
- Temporary artifacts

These must be reproducible from Tier 0.

---

### 3.2 Ingestion Is a First-Class Pipeline

Anything entering the system follows a deterministic path:

1. **Capture**
   - raw data stored as a blob
2. **Normalize**
   - text extraction, cleaning, structure
3. **Anchor**
   - metadata + references written to Obsidian
4. **Index**
   - embeddings, search indexes (derived)
5. **Reflect**
   - optional summarization or synthesis

Obsidian stores *meaning and references*, never raw blobs.

---

### 3.3 Memory Promotion Is a Privileged Operation

Only the agent memory manager (Letta) may promote durable memory.

Other components may:
- propose memory
- reference memory
- query memory

But only Letta may **commit** memory to Obsidian.

This ensures:
- consistency
- deduplication
- conflict resolution
- auditability

---

### 3.4 Human-Auditable Memory

Promoted memory must be:
- readable without tooling
- diffable
- attributable
- minimally verbose

Memory is written *for the human first*, the machine second.

---

## 4. Intent, Not Commands

The system operates on **intent**, not imperative instructions.

Examples:
- “Remind me to follow up” → creates a commitment
- “Remember this preference” → proposes memory
- “Watch this page” → establishes a watcher with conditions

The system is responsible for:
- interpreting intent
- choosing the right level of action
- asking clarifying questions only when necessary

---

## 5. Commitments and Loop Closure

A core responsibility of Brain OS is to help close loops.

- reminders, tasks, and scheduled actions are **commitments**
- commitments have owners, deadlines, and provenance
- missed commitments are analyzed, not ignored

The system must support:
- retrospection
- pattern recognition
- gentle correction, not punishment

An unclosed loop is a signal, not a failure.

---

## 6. Skills, Not Scripts

Reusable capability is expressed as **skills**.

A skill:
- has a clear input/output contract
- is testable
- has bounded authority
- produces inspectable artifacts

Examples:
- “Clip and summarize a URL”
- “Prepare a meeting brief”
- “Weekly review and plan”
- “Digest changes from watched sources”

Skills are the unit of compounding leverage.

---

## 7. The Attention Router

All outputs flow through an attention routing layer that decides:

- **whether** to notify
- **when** to notify
- **how** to notify
- **how much** to say

Channels (Signal, Web UI, Obsidian notes) are chosen deliberately.

No component may bypass this router.

---

## 8. Trust, Autonomy, and Safety

Autonomy is contextual and tiered.

Example levels:
- L0: suggest only
- L1: draft + approval
- L2: reversible actions
- L3: bounded automatic actions

Levels are assigned per:
- capability
- context
- actor

All autonomy must be:
- visible
- reviewable
- revocable

---

## 9. Success Criteria

The system is successful if:

- important things are not forgotten
- interruptions feel intentional, not noisy
- commitments are reliably closed
- knowledge compounds instead of stagnates
- the human trusts the system more over time

If the system becomes clever but untrustworthy, it has failed.

---

## 10. The North Star

> “I can throw anything at my system and trust that it will be captured, understood, turned into durable knowledge when appropriate, and converted into action with the right level of autonomy — without ever sacrificing privacy or flooding my attention.”

This document is the contract that makes that possible.

Any future feature, integration, or optimization must be consistent with these principles.

If it is not, it does not belong.