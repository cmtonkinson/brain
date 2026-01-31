# PRD: Provenance System
## Traceable Evidence and Chain-of-Custody for Brain

---

## 1. Overview

### Feature Name
**Provenance System**

### Summary
Introduce a **first-class provenance subsystem** that records where information came from, how it was produced, and how it relates to other data. Provenance is stored in **Postgres (Tier 0)** and linked to some durable artifacts (commitments, memory, decisions, etc.) so that Brain can answer:

> "Why does the system believe this?"

This system provides a **normalized, queryable, and auditable** chain-of-custody across ingestion, reasoning, and action.

---

## 2. Problem Statement

Brain is designed to be trustworthy and auditable. Today, provenance is mentioned across multiple PRDs but has no unified schema or service contract. This creates risk:

- inconsistent provenance formats across subsystems
- loss of traceability for derived or inferred data
- inability to debug reasoning or automation outcomes
- erosion of trust in long-lived data

We need a **cohesive provenance substrate** that every subsystem can depend on.

---

## 3. Goals and Non-Goals

### Goals
- Provide a normalized, system-wide provenance schema
- Support chain-of-custody for derived data
- Make provenance human-auditable and easy to render
- Keep provenance append-only

### Non-Goals
- Full causal reasoning graph or lineage visualization UI
- Automatic reconciliation of conflicting provenance
- Storing raw artifacts inside provenance records (references only)
- Replacing subsystem-specific metadata (e.g., notification envelopes)

---

## 4. Design Principles

1. **Truth is explicit**
2. **Provenance is normalized, not embedded JSON**
3. **No silent edits or deletions**
4. **Human-auditable by default**
5. **Tier 0 durability applies**

---

## 5. Core Concepts

### 5.1 Provenance Record
A **ProvenanceRecord** captures how a piece of data was produced:
- who or what produced it
- which subsystem initiated it
- whether it was direct capture, inference, or transformation
- was this derived from some parent ProvenanceRecord?

### 5.2 Provenance Input
**ProvenanceInput** entries reference the specific source material used:
- Signal message ID
- email message ID
- calendar event ID
- Obsidian note path
- MinIO object ID
- MCP operation reference

### 5.3 Provenance Link
**ProvenanceLink** entries connect provenance to artifacts (commitments, memory notes, decisions, etc.) and store the **confidence** of that artifact at creation time.

---

## 6. Functional Requirements

### 6.2 Data Model (Normalized)

Minimum tables (names may be adjusted to match conventions):

#### 6.2.1 `provenance_records`
- `id` (UUID, PK)
- `source_component` (string, required)
- `origin_signal` (string, required)
- `actor_type` (enum: `user`, `system`, `agent`, `external`)
- `actor_reference` (string, optional)
- `method` (enum: `captured`, `inferred`, `transformed`)
- `created_at` (UTC)

#### 6.2.2 `provenance_inputs`
- `id` (UUID, PK)
- `provenance_id` (FK -> provenance_records.id)
- `input_type` (string; e.g., `signal`, `email`, `calendar`, `file`, `obsidian`, `minio`, `mcp`)
- `reference` (string, required; opaque identifier)
- `description` (text, optional)
- `captured_at` (UTC, optional)

#### 6.2.3 `provenance_links`
- `id` (UUID, PK)
- `provenance_id` (FK -> provenance_records.id)
- `entity_type` (string; e.g., `commitment`, `memory`, `decision`, `notification`)
- `entity_id` (string or UUID)
- `confidence` (float 0-1; nullable if unknown)
- `created_at` (UTC)

#### 6.2.4 `provenance_relations`
- `id` (UUID, PK)
- `child_provenance_id` (FK -> provenance_records.id)
- `parent_provenance_id` (FK -> provenance_records.id)
- `relation_type` (enum: `derived_from`, `summarized_from`, `extracted_from`, `inferred_from`)
- `created_at` (UTC)

Notes:
- Provenance is **append-only**. No updates in place other than metadata corrections (which must be audited).
- All identifiers are stored in UTC, converting to local time when rendering.

### 6.3 Creation Requirements

#### 6.3.1 Direct Capture
When a user or system captures input (Signal message, email, file, etc.), create:
- a ProvenanceRecord
- one or more ProvenanceInputs
- a ProvenanceLink to the resulting artifact(s)

#### 6.3.2 Inference / Derivation
When data is derived (summaries, inferred commitments, extracted facts):
- create a new ProvenanceRecord
- link it to parent provenance via `provenance_relations`
- include model/tool identifiers in `source_component` and `origin_signal`

#### 6.3.3 Manual Overrides
User edits to a Tier 0 artifact must:
- create a new ProvenanceRecord (method `captured`)
- link to the updated artifact
- optionally link to prior provenance as `derived_from`

### 6.5 Rendering and Retrieval

The provenance service must provide:
- **summary view**: short, human-readable provenance string
- **full view**: detailed chain (inputs + relations)

Example summary:
> "Signal message from Chris (2026-01-31) + calendar event id=xyz; inferred by agent."

### 6.6 Obsidian References (Optional)

Obsidian notes may include a minimal provenance block:
- `provenance_id`
- `source_summary`

This is **read-only**, for human inspection only, and does not affect canonical storage.

---

## 7. Integration Points

### 7.1 Universal Ingestion Pipeline
Subsystems will have the ability to register "hooks" against the ingestion pipeline to extract, transform, summarize,
analyze, reason, and synthesize from/with incoming data.

Before a hook callback is invoked, the ingestion pipeline must create a new ProvenanceRecord for that data, and pass
that record to the hook callback with whatever other parameters are necessary.

If and when entities (memories, schedules, commitments, etc.) are subsequently created, by the called code, they must
encode the provenance ID in their metadata. If derived data is created, then child ProvenanceRecords should be generated
accordingly.

### 7.2 Commitment Tracking (CTLC) Example:
- `commitments.provenance_id` points to `provenance_records.id`
- `commitment_progress.provenance_id` points to provenance for the progress signal

### 7.3 Memory Promotion Example:
- Letta must attach provenance when promoting memory.
- Obsidian memory notes may surface provenance summary with a `provenance_id` reference

---

## 8. Observability and Audit

The system must log:
- provenance creation events
- relation creation events
- invalid or missing provenance failures

Audit records must be queryable by:
- entity_id
- source_component
- input_type
- time range

---

## 10. Success Metrics

- Provenance chains are auditable within one query

---

## 11. Definition of Done

- [ ] Provenance tables and migrations created
- [ ] Provenance service interface defined
- [ ] Ingestion pipeline emits provenance records
- [ ] Commitment tracking integrates provenance
- [ ] There is a clear public API for the provenance service

---

## 12. Alignment with Brain Manifesto

- **Truth Is Explicit:** provenance and confidence recorded
- **Sovereignty First:** canonical provenance stored locally in Postgres
- **Memory Is Curated:** provenance supports memory review and trust
- **Everything Compounds:** provenance improves future reasoning

---

_End of PRD_
