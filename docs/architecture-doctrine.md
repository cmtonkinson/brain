# Brain — Architecture Doctrine
This document defines the **architectural doctrine** of Brain: the
non-negotiable principles governing data authority, system boundaries, and
rebuild strategy.

This is not a feature description.  
It is the **constitution** the system must obey as it evolves.

---
## Core Doctrine
### 1. Authority Is Explicit

Every piece of data in Brain must have a clear answer to:
> “Is this authoritative, or can it be rebuilt?”

There is no ambiguous middle ground.

---
### 2. One-Way Promotion
Data may move:
- Tier 1 → Tier 0 (via Letta promotion)
- Tier 2 → discarded

No automatic reverse flow.

---
### 3. Canonical Memory and System Authority
If it matters long-term, it must:
- exist in Obsidian
- be readable by a human
- carry provenance

Operational commitments, schedules, and other structured system state are
canonical in Postgres. Obsidian is the canonical memory for promoted,
human-readable knowledge.

---
### 4. Rebuildability Is a Requirement
The system must tolerate:
- full loss of embeddings
- full loss of derived artifacts
- partial system failure

Rebuild must be possible from Tier 0 + Tier 1.

---
## Architectural Invariants
- Skills cannot write durable memory directly
- Policies gate all side effects
- Attention routing gates all interruptions
- Memory governance is ongoing, not one-time

---

_End of doctrine_
