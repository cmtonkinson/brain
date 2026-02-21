# A Manifesto for Personal Cognitive Infrastructure
This project is highly opinionated; less of a general purpose AI assistant than
a private operating system for attention, memory, and action.

> "I can throw anything at my system and trust that it will be captured,
> understood, turned into durable knowledge when appropriate, and converted into
> action with the right level of autonomy — without ever sacrificing privacy or
> abusing my attention."
> -Chris

This document is the architecture and design contract for the system: every
feature, integration, and optimization must be consistent with these principles,
otherwise it doesn't belong.

---
## 1. Purpose (The Why)
Modern knowledge work suffers from a fundamental asymmetry:
- Capture is cheap; understanding is expensive.
- Planning is easy; execution is fragile.
- Memory is abundant; trust is scarce.
- Automation is powerful; autonomy is dangerous.

**Brain exists to restore balance.**

Its purpose is to:
- _exploit knowledge_ whenever useful,
- translate intent into _successful action_,
- and do so in a way that is private, auditable, and trustworthy.

A well-crafted exocortex should feel, in practice, less like "AI" and more like
a calm, competent partner.

---
## 2. Core First Principles (Non-Negotiable)
### 2.1 Sovereignty First
All authoritative data must be owned, inspectable, and portable.
- Local-first by default
- No silent cloud dependencies
- No opaque state that cannot be audited

Brain SHOULD be convenient, but MUST be private.

**LLM Backend:** At release-time in early 2026, the risk/reward balance may
still tilt toward using a frontier model from a major lab (GPT from OpenAI,
Sonnet/Opus from Anthropic, Gemini from Google) via API but local models hosted
by Ollama are first class citizens and can be very useful.

---
### 2.2 Truth Is Explicit
The system must distinguish between:
- **facts**
- **claims**
- **inferences**
- **summaries**
- **guesses**

The system must never pretend certainty where none exists. Every durable
artifact must carry:
- provenance (where it came from)
- confidence (how sure we are)
- reversibility (how easily it can be undone)

---
### 2.3 Attention Is Sacred
Interruptions are the most expensive resource. The system must:
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

---
### 2.6 Everything Must Compound
The system should get better over time, not just bigger.
- skills should be reusable
- knowledge should reduce future effort
- mistakes should feed learning
- repetition should create leverage

---
## 3. Architectural Doctrine
### 3.1 Layered Data Model
The system is composed of data tiers with explicit boundaries.

#### Tier 0 — Authoritative Truth
**Prioritize backups** for this data at all costs:
- Obsidian vault (Markdown knowledge, promoted memory)
- Postgres (authoritative system state and commitments)
- Object storage (raw blobs: HTML, PDFs, audio, images)

---
#### Tier 1 — System State
Loss of data here would be painful, but not crippling:
- Agent memory store (Letta internal state)
- Scheduler / job state
- Message linkage state (e.g. Signal CLI identity)

---
#### Tier 2 — Derived / Cache
All of this is rebuildable:
- Vector indexes
- Embeddings
- Summaries
- Temporary artifacts

---
### 3.2 Ingestion Is a First-Class Pipeline
Anything entering the system follows a deterministic path.
1. **Capture** - raw data stored as a blob
2. **Normalize** - text extraction, cleaning, structure
3. **Anchor** - metadata + references written to Obsidian
4. **Index** - embeddings, search indexes (derived)
5. **Reflect** - optional summarization or synthesis

---
### 3.3 Memory Promotion Is a Privileged Operation
Any component may propose, reference, and query memory, but only the memory
manager (Letta) may promote information into durable memory (meaning commit
memory into Obisidian). This ensures:
- consistency
- deduplication
- conflict resolution
- auditability

---
### 3.4 Human-Auditable Memory
Because memories are written _for the human first_ (and the machine second),
promoted memory must be:
- readable without tooling
- attributable
- minimally verbose


---
## 4. Intent, Not Commands
The system operates on **intent**, not imperative instructions. Examples:
- “I have to prep before that meeting” → creates a commitment
- “Remember this preference” → proposes memory
- “Watch this page” → establishes a watcher with conditions

The system is responsible for:
- interpreting intent
- choosing the right level of action
- asking clarifying questions [only] when necessary

---
## 5. Commitments and Loop Closure
A core responsibility of Brain is to help close loops.
- reminders, tasks, and scheduled actions are **commitments**
- commitments have owners, deadlines, and provenance
- missed commitments are analyzed, not ignored

The system must support retrospection, pattern recognition, and correction. An
unclosed loop is a signal, not a failure.

---

## 6. Capabilities, Not Scripts
Reusable Capability is expressed as **Ops** and **Skills**: the units of compounding
leverage within the system. A Capability:
- has a clear input/output contract
- is testable
- has bounded authority
- produces inspectable results

Examples:
- “Clip and summarize a URL”
- “Prepare a meeting brief”
- “Weekly review and plan”
- “Digest changes from watched sources”

---
## 7. The Attention Router
All outputs flow through an attention routing layer that decides:
- **whether** to notify
- **when** to notify
- **how** to notify
- **how much** to say

Output channels (e.g. Signal) are chosen deliberately.

_No component may bypass this router._ In fact, there are automated test gates
to ensure callsites do not violate this principle.

---
## 8. Trust, Autonomy, and Safety
Autonomy is contextual and tiered. Levels:
- L0: suggest only
- L1: draft + approval
- L2: reversible actions
- L3: bounded automatic actions

Levels are assigned per capability, context, and actor. All autonomy must be
visible, reviewable, and revocable.

---
## 9. Success Criteria
The system is successful if:
- important things are not forgotten
- interruptions feel intentional, not noisy
- commitments are reliably closed
- knowledge compounds instead of stagnates
- the human trusts the system more over time

If the system becomes clever but untrustworthy, **It. Has. Failed.**

---
_End of Manifesto_
