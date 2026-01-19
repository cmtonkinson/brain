# PRD: Memory Promotion via Letta
## Controlled Promotion of Durable Memory into Obsidian for Brain

---

## 1. Overview

### Feature Name
**Memory Promotion Authority (Letta → Obsidian)**

### Summary
Grant **Letta** (the agent memory manager) exclusive authority to **promote stable, human-meaningful memories** into a dedicated Obsidian folder, making Obsidian the **canonical store of durable memory** while Letta remains the high-performance working memory system.

This feature introduces a deliberate, auditable boundary between:
- ephemeral and operational agent memory
- durable, human-auditable knowledge

---

## 2. Problem Statement

Without explicit memory governance, agent systems tend to:
- accumulate noisy or contradictory “memories”
- blur the line between transient context and durable truth
- silently turn internal databases into the only copy of important knowledge

Brain requires a **clear doctrine of memory authority** so that:
- durable memory is intentional
- humans can audit what the system “knows”
- loss of agent state does not imply loss of knowledge

---

## 3. Goals and Non-Goals

### Goals
- Make Obsidian the canonical store for promoted memory
- Grant Letta sole authority to promote memory
- Ensure promoted memory is human-readable and auditable
- Preserve Letta as a working memory, not a source of truth
- Prevent other components from writing durable memory directly

### Non-Goals
- Mirroring all Letta memory into Obsidian
- Real-time synchronization between Letta and Obsidian
- Automatic promotion of every inferred preference
- Allowing schedulers, watchers, or UIs to write memory directly

---

## 4. Design Principles

1. **Memory is curated, not accumulated**
2. **Durable memory must be intentional**
3. **Promotion is a privileged operation**
4. **Humans must be able to read and audit memory**
5. **Agent state is not authoritative knowledge**

---

## 5. Memory Taxonomy

### 5.1 Memory Classes

1. **Ephemeral Memory**
   - conversation context
   - short-term reasoning state
   - never promoted

2. **Operational Memory**
   - tool preferences
   - workflow hints
   - optionally promotable

3. **Declarative / Durable Memory**
   - user preferences
   - policies and rules
   - architectural decisions
   - commitments and standing agreements
   - always promoted if accepted

Only class (3) is guaranteed to be written to Obsidian.

---

## 6. Authority Model

### 6.1 Exclusive Promotion Authority

- Only Letta may invoke the **memory promotion tool**
- All other components may only:
  - propose memory
  - reference existing memory
  - query memory

This creates a single choke point for memory quality and consistency.

---

### 6.2 Proposal Flow

Other components (watchers, schedulers, UIs) emit **memory proposals**:

```json
{
  "type": "memory_proposal",
  "source": "scheduler:daily-brief",
  "candidate": {
    "category": "preference",
    "content": "Prefers weekday briefings at 8am",
    "confidence": 0.82
  }
}
```

Letta evaluates proposals and decides whether to promote.

---

## 7. Functional Requirements

### 7.1 Memory Promotion Tool (MCP)

Letta must have access to a single MCP tool, e.g.:

```
promote_memory_to_obsidian(
  category,
  title,
  content,
  provenance,
  confidence
)
```

Tool behavior:
- writes a Markdown note or updates a canonical file
- enforces schema and required metadata
- records timestamp and source
- returns the Obsidian path or identifier

---

### 7.2 Obsidian Storage Location

All promoted memory is written under a dedicated folder, e.g.:

```
Brain/Memory/
  Preferences.md
  Policies.md
  Decisions.md
  Projects/
```

This folder is treated as **Tier 0 authoritative data**.

---

### 7.3 Back-Reference Handling

After promotion:
- Letta stores a reference to the Obsidian note
- Optional checksum or version identifier is recorded
- Letta treats Obsidian as canonical for that memory

---

## 8. Security and Safety

- Promotion is a **write action** and subject to policy checks
- Memory writes may require human confirmation depending on category
- No automated background job may promote memory without agent review

---

## 9. Observability and Audit

Each promotion must be logged with:
- timestamp
- initiating actor
- source of inference
- category
- confidence score
- Obsidian path

Optional:
- periodic “memory review” notes generated for human inspection

---

## 10. Backup and Recovery

- Obsidian memory folder is Tier 0 and must be backed up
- Letta/Postgres memory is Tier 1 (reconstructable)
- On restart, Letta may re-ingest promoted memory from Obsidian

---

## 11. Risks and Mitigations

### Risk: Memory Noise
Mitigation:
- promotion rubric
- confidence thresholds
- human confirmation for sensitive categories

### Risk: Dual Truth Sources
Mitigation:
- Obsidian is canonical
- Letta stores references, not copies

---

## 12. Success Metrics

- Promoted memory remains small and high-signal
- Humans can explain why each memory exists
- Loss of Letta state does not imply loss of knowledge
- Reduced contradiction and duplication in memory

---

## 13. Definition of Done

- [ ] Promotion tool implemented and gated
- [ ] Letta can promote approved memories
- [ ] Other components restricted to proposals only
- [ ] Obsidian memory folder created and documented
- [ ] Audit logging in place

---

## 14. Alignment with Brain Manifesto

- **Memory Is Curated:** deliberate promotion only
- **Truth Is Explicit:** provenance and confidence recorded
- **Sovereignty First:** durable memory is local and auditable
- **Everything Compounds:** stable knowledge improves future behavior

---

_End of PRD_
