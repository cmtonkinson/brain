# Brain OS — Architecture Doctrine
## Authority, Data Classes, and Rebuildability

---

## Purpose

This document defines the **architectural doctrine** of Brain OS: the non-negotiable principles governing data authority, system boundaries, and rebuild strategy.

This is not a feature description.  
It is the **constitution** the system must obey as it evolves.

---

## Core Doctrine

### 1. Authority Is Explicit

Every piece of data in Brain OS must have a clear answer to:
> “Is this authoritative, or can it be rebuilt?”

There is no ambiguous middle ground.

---

### 2. Data Classes

#### Tier 0 — Authoritative, Human-Owned
Must be backed up. Cannot be regenerated.

- Obsidian vault
  - Memory folder (promoted memories)
  - Notes, reflections, decisions
- User-authored documents
- Explicit configuration and policy files

Loss here is **irrecoverable knowledge loss**.

---

#### Tier 1 — Durable System State
Important, but reconstructable with effort.

- MinIO object storage (raw artifacts)
- Commitment records
- Schedule definitions
- Message metadata
- Letta Postgres state

Loss is painful but recoverable.

---

#### Tier 2 — Derived / Cached
Always disposable.

- Embeddings (Qdrant)
- Summaries
- Indexes
- Extracted/normalized text
- Search caches

Never back these up unless for convenience.

---

### 3. One-Way Promotion

Data may move:
- Tier 1 → Tier 0 (via Letta promotion)
- Tier 2 → discarded

No automatic reverse flow.

---

### 4. Obsidian Is the Canonical Memory

If it matters long-term, it must:
- exist in Obsidian
- be readable by a human
- carry provenance

No database is allowed to become the “real brain.”

---

### 5. Rebuildability Is a Requirement

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
