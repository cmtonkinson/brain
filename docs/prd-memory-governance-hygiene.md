# PRD: Memory Governance & Hygiene
## Deduplication, Conflict Resolution, Drift Control, and Review for Brain

---

## 1. Overview

### Feature Name
**Memory Governance & Hygiene**

### Summary
Introduce a **memory governance layer** for Brain that actively manages the quality, consistency, and relevance of durable memory over time.

This feature adds:
- deduplication
- conflict detection and resolution
- expiration and decay
- provenance tracking
- periodic review jobs

The goal is to prevent **memory drift**, reduce entropy, and maintain long-term trust in what the system “knows.”

---

## 2. Problem Statement

Without explicit hygiene, memory systems degrade:

- duplicate memories accumulate
- outdated preferences persist indefinitely
- conflicting facts coexist silently
- inferred beliefs lose provenance
- humans lose trust in the system’s memory

Brain treats memory as **curated knowledge**, not an append-only log.  
This requires ongoing governance, not just careful promotion.

---

## 3. Goals and Non-Goals

### Goals
- Maintain a high-signal, low-noise memory store
- Detect and resolve duplicate or overlapping memories
- Surface conflicts explicitly
- Support memory expiration and decay
- Preserve provenance and confidence
- Provide regular, human-auditable reviews

### Non-Goals
- Automatic deletion of durable memory without review
- Perfect factual correctness
- Realtime consistency guarantees
- Fully autonomous memory pruning

---

## 4. Design Principles

1. **Memory must earn its permanence**
2. **Conflicts are signals, not errors**
3. **Nothing is forgotten silently**
4. **Humans remain the final authority**
5. **Memory quality compounds over time**

---

## 5. Memory Metadata Requirements

Every promoted memory must include:

- category (preference, policy, fact, decision, commitment)
- content (human-readable)
- provenance (source + method of inference)
- confidence score (0–1)
- created_at timestamp
- last_reviewed_at timestamp (optional)
- expiration_hint (optional)

This metadata enables governance without re-ingestion.

---

## 6. Governance Capabilities

### 6.1 Deduplication

#### Description
Identify memories that are:
- semantically equivalent
- overlapping
- redundant

#### Mechanisms
- embedding similarity on memory content
- category-specific heuristics
- identical provenance detection

#### Outcome
- propose merge
- propose replacement
- mark as confirmed duplicate

No automatic deletion occurs without review.

---

### 6.2 Conflict Detection

#### Description
Detect memories that assert incompatible claims.

Examples:
- “Prefers email notifications” vs “Never send email”
- “Daily brief at 8am” vs “Daily brief at 9am”

#### Mechanisms
- category-aware contradiction rules
- semantic comparison
- temporal precedence (newer vs older)

#### Outcome
- flag conflict
- request human clarification
- record resolution decision

---

### 6.3 Expiration & Decay

#### Description
Support memories that:
- are time-bound
- lose relevance
- apply only within a project or phase

#### Mechanisms
- explicit expiration hints
- confidence decay over time
- inactivity-based review triggers

Expired memories are:
- archived, not deleted
- excluded from default reasoning unless reactivated

---

### 6.4 Provenance Enforcement

#### Description
Ensure every memory answers:
> “Why does the system believe this?”

#### Mechanisms
- required provenance fields
- provenance surfaced in reviews
- low-confidence memories prioritized for review

---

## 7. Review Job (Scheduled Governance)

### 7.1 Periodic Review

A scheduled job (e.g. weekly or monthly) performs:

- scan for duplicates
- scan for conflicts
- identify stale or expired memories
- rank memories by risk (low confidence, old, high impact)

---

### 7.2 Review Output

The review job produces:
- a structured report
- a human-readable Obsidian note

Example sections:
- “Potential Duplicates”
- “Conflicting Memories”
- “Memories Pending Review”
- “Expired / Archived Memories”

This note becomes the **human intervention point**.

---

## 8. Human-in-the-Loop Resolution

Humans may:
- approve merges
- resolve conflicts
- extend or expire memories
- downgrade confidence
- mark memory as canonical

All decisions are logged and attributed.

---

## 9. Agent Behavior During Drift

When conflicts or low-confidence memories exist:
- agent must acknowledge uncertainty
- agent may ask clarifying questions
- agent must avoid asserting contested facts

This prevents confident-but-wrong behavior.

---

## 10. Observability & Audit

The system must log:
- governance checks performed
- conflicts detected
- review outcomes
- memory lifecycle events (created, merged, archived)

Optional:
- memory change history per item

---

## 11. Risks and Mitigations

### Risk: Over-Pruning
Mitigation:
- human confirmation
- archive instead of delete

### Risk: Review Fatigue
Mitigation:
- prioritization by impact
- batching
- clear summaries

---

## 12. Success Metrics

- Reduced duplicate memory count
- Fewer unresolved conflicts
- Stable memory size over time
- Increased human trust and confidence
- Clear provenance for all durable memories

---

## 13. Definition of Done

- [ ] Memory metadata schema enforced
- [ ] Deduplication logic implemented
- [ ] Conflict detection implemented
- [ ] Expiration handling implemented
- [ ] Scheduled review job running
- [ ] Human-readable review notes generated

---

## 14. Alignment with Brain Manifesto

- **Memory Is Curated:** hygiene is ongoing
- **Truth Is Explicit:** conflicts and provenance surfaced
- **Attention Is Sacred:** reviews are batched and intentional
- **Everything Compounds:** cleaner memory improves all reasoning

---

_End of PRD_
