# Manifesto
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

------------------------------------------------------------------------
## Core First Principles (Non-Negotiable)
### Sovereignty First
All authoritative data must be owned, inspectable, and portable.
- Local-first by default
- No silent cloud dependencies
- No opaque state that cannot be audited

Brain SHOULD be convenient, but MUST be private.

**LLM Backend:** At release-time in early 2026, the risk/reward balance may
still tilt toward using a frontier model from a major lab (GPT from OpenAI,
Sonnet/Opus from Anthropic, Gemini from Google) via API but local models hosted
by Ollama are first class citizens and can be very useful.

### Truth Is Explicit
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

### Attention Is Sacred
Interruptions are the most expensive resource. The system must:
- batch when possible
- defer when appropriate
- escalate only when necessary
- respect time, focus, and context

Silence is a valid and often optimal outcome.

### Memory Is Curated, Not Accumulated
Memory is not storage.
- Most things should be forgotten.
- Some things should be summarized.
- Very few things should be remembered permanently.

Durable memory must be:
- stable
- meaningful
- human-auditable
- intentionally promoted

### Actions Are Bounded
The system may suggest freely.
It may draft cautiously.
It may act only within explicit, reviewable boundaries.

### Everything Must Compound
The system should get better over time, not just bigger.
- skills should be reusable
- knowledge should reduce future effort
- mistakes should feed learning
- repetition should create leverage

------------------------------------------------------------------------
## Architectural Doctrine
### Data Authority
Every piece of data in Brain must have a clear answer to: _"Is this
authoritative, or can it be rebuilt?"_ There is no ambiguous middle ground.

- **One-Way Promotion.** Data may move from operational to canonical (via Letta
  promotion) or from derived to discarded. No automatic reverse flow.
- **Canonical Memory.** If it matters long-term, it must exist in Obsidian, be
  readable by a human, and carry provenance. Operational commitments, schedules,
  and other structured system state are canonical in Postgres.
- **Rebuildability.** The system must tolerate full loss of embeddings, full loss
  of derived artifacts, and partial system failure. Rebuild must be possible from
  authoritative and operational sources alone.

### Ingestion Is a First-Class Pipeline
Anything entering the system follows a deterministic path.
1. **Capture** - raw data stored as a blob
2. **Normalize** - text extraction, cleaning, structure
3. **Anchor** - metadata + references written to Obsidian
4. **Index** - embeddings, search indexes (derived)
5. **Reflect** - optional summarization or synthesis

### Memory Promotion Is a Privileged Operation
Any component may propose, reference, and query memory, but only the memory
manager (Letta) may promote information into durable memory (meaning commit
memory into Obsidian). This ensures:
- consistency
- deduplication
- conflict resolution
- auditability

### Human-Auditable Memory
Because memories are written _for the human first_ (and the machine second),
promoted memory must be:
- readable without tooling
- attributable
- minimally verbose

------------------------------------------------------------------------
## Intent, Not Commands
The system operates on **intent**, not imperative instructions. Examples:
- "I have to prep before that meeting" → creates a commitment
- "Remember this preference" → proposes memory
- "Watch this page" → establishes a watcher with conditions

The system is responsible for:
- interpreting intent
- choosing the right level of action
- asking clarifying questions [only] when necessary

------------------------------------------------------------------------
## Commitments and Loop Closure
A core responsibility of Brain is to help close loops.
- reminders, tasks, and scheduled actions are **commitments**
- commitments have owners, deadlines, and provenance
- missed commitments are analyzed, not ignored

The system must support retrospection, pattern recognition, and correction. An
unclosed loop is a signal, not a failure.

------------------------------------------------------------------------
## Capabilities, Not Scripts
Reusable _Capability_ is expressed as _Ops_ and _Skills_: the units of
compounding leverage within the system. A _Capability_:
- has a clear input/output contract
- is testable
- has bounded authority
- produces inspectable results

Examples:
- "Clip and summarize a URL"
- "Prepare a meeting brief"
- "Weekly review and plan"
- "Digest changes from watched sources"

------------------------------------------------------------------------
## The Attention Router
All outputs flow through an attention routing layer that decides:
- **whether** to notify
- **when** to notify
- **how** to notify
- **how much** to say

Output channels (e.g. Signal) are chosen deliberately.

_No component may bypass this router._ In fact, there are automated test gates
to ensure callsites do not violate this principle.

------------------------------------------------------------------------
## Trust, Autonomy, and Safety
Autonomy is contextual and tiered. Levels:
- L0: suggest only
- L1: draft + approval
- L2: reversible actions
- L3: bounded automatic actions

Levels are assigned per capability, context, and actor. All autonomy must be
visible, reviewable, and revocable.

------------------------------------------------------------------------
## Success Criteria
The system is successful if:
- important things are not forgotten
- interruptions feel intentional, not noisy
- commitments are reliably closed
- knowledge compounds instead of stagnates
- the human trusts the system more over time

If the system becomes clever but untrustworthy, **It. Has. Failed.**

------------------------------------------------------------------------
## Architectural Invariants
These are constitutional constraints. They are non-negotiable and must hold at
all times, regardless of feature scope or implementation convenience.

- _Skills_ cannot write durable memory directly.
- Policies gate all side effects.
- Attention routing gates all interruptions.
- Memory governance is ongoing, not one-time.

------------------------------------------------------------------------
_End of Manifesto_
