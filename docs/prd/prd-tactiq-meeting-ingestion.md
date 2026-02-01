# PRD: Tactiq.io Meeting Notes Ingestion
## Automatic Capture and Processing of Meeting Knowledge for Brain

---

## 1. Overview

### Feature Name
**Tactiq Meeting Notes Ingestion**

### Summary
Integrate **Tactiq.io** as a first-class ingestion source for Brain, enabling automatic capture, processing, and organization of meeting transcripts and downstream proposals.

This feature routes Tactiq outputs through the **Universal Ingestion Pipeline**, ensuring meeting knowledge is preserved as raw artifacts, normalized text, metadata, embeddings, and anchored Obsidian notes — without bypassing governance, memory promotion, or attention policies.

---

## 2. Problem Statement

Meetings generate high-value information:
- decisions
- commitments
- context
- rationale

But this information is often:
- siloed in third-party tools
- inconsistently summarized
- quickly forgotten
- disconnected from commitments and memory systems

Brain needs a reliable way to **turn meetings into durable, structured knowledge** without manual copy-paste or ad-hoc workflows.

---

## 3. Goals and Non-Goals

### Goals
- Automatically ingest Tactiq meeting artifacts
- Preserve raw transcripts for audit and reprocessing
- Normalize meeting notes into human-readable anchors
- Extract commitments and decisions (as proposals)
- Integrate with memory, commitments, and attention systems

### Non-Goals
- Replacing Tactiq’s transcription or UI
- Real-time meeting participation
- Automatic memory promotion without review
- Acting on meeting content without policy gating
- Automatic summarization of ingested meeting content

---

## 4. Design Principles

1. **Meetings are ingestion events**
2. **Raw transcripts are authoritative artifacts**
3. **Derived insights are proposals, not facts**
4. **Commitments must be closed explicitly**
5. **Silence is acceptable after ingestion**

---

## 5. Ingestion Flow

```
Tactiq Export / Webhook / API
   ↓
Universal Ingestion Pipeline
   ↓
Object store (raw transcript + metadata)
   ↓
Extraction & Normalization
   ↓
Obsidian Anchor Note (Meeting)
   ↓
Derived Indexing (embeddings)
```

---

## 6. Functional Requirements

### 6.1 Source Integration

The system must support ingesting from Tactiq via one or more of:
- API access
- export files (e.g. Markdown, text, JSON)
- webhook or polling mechanism

Each ingestion event must include:
- meeting title
- date/time
- participants (if available)
- source platform (Zoom, Meet, Teams, etc.)

---

### 6.2 Raw Artifact Storage

Store the following in the object store:
- full transcript
- Tactiq-generated summary (if provided, stored as raw artifact only)
- speaker metadata (if available)
- source metadata

Raw artifacts are **Tier 1 authoritative inputs**.

---

### 6.3 Normalization

Normalize transcripts into:
- readable Markdown
- speaker-attributed sections
- timestamps (if available)

Noise (filler words, transcription artifacts) may be lightly cleaned, but **verbatim content must remain reconstructable**.

---

### 6.4 Obsidian Anchor Note

Create a meeting note with:
- title and date
- participants
- links to raw blobs
- normalized transcript reference
- tags (e.g. `meeting`, `source:tactiq`)

Anchoring must trigger an incremental indexer update.

Example location:
```
Meetings/2026/2026-03-12 Project Sync.md
```

---

### 6.5 Derived Insights (Optional)

The agent may propose:
- extracted action items
- decisions
- open questions
- follow-ups

These are treated as:
- **commitment proposals**
- **memory proposals**

No automatic promotion or scheduling occurs without policy approval.

---

## 7. Integration with Other Systems

### 7.1 Commitment Tracking
- Action items become proposed commitments
- Each proposal links back to the meeting note
- Missed commitments reference the originating meeting

---

### 7.2 Memory Promotion
- Repeated or stable decisions may be proposed for memory
- Promotion authority remains with Letta

---

### 7.3 Attention Router
- Ingestion itself is silent by default
- Optional digest inclusion (“New meeting ingested”)
- Escalation only if explicit follow-up required

---

## 8. Policy & Autonomy

- Default autonomy: **L2 (bounded automatic ingestion)**
- Extraction and summarization allowed
- Scheduling or messaging requires approval
- No outbound communication without routing

---

## 9. Observability & Audit

Log:
- ingestion timestamp
- source meeting ID
- artifacts stored
- derived proposals generated
- downstream actions (if any)

Traces must link meeting ingestion to:
- commitments
- memory proposals
- later actions

---

## 10. Security & Privacy

- Treat transcripts as sensitive data
- Never expose transcripts to external services unintentionally
- Respect participant confidentiality
- Support redaction if required by policy

---

## 11. Risks and Mitigations

### Risk: Over-Summarization
Mitigation:
- preserve raw transcript
- summaries marked as derived

### Risk: False Commitments
Mitigation:
- treat all extracted actions as proposals
- require confirmation

---

## 12. Success Metrics

- Meetings captured without manual effort
- Action items tracked and closed
- Decisions retained and auditable
- Reduced “what did we decide?” confusion
- High trust in meeting-derived knowledge

---

## 13. Definition of Done

- [ ] Tactiq ingestion source implemented
- [ ] Raw artifacts stored in the object store
- [ ] Normalized transcripts generated
- [ ] Obsidian meeting notes created
- [ ] Commitment/memory proposals supported
- [ ] Observability traces linked

---

## 14. Alignment with Brain Manifesto

- **Truth Is Explicit:** transcripts preserved
- **Memory Is Curated:** meetings propose, not assert
- **Everything Compounds:** meetings become leverage
- **Attention Is Sacred:** ingestion is silent by default

---

_End of PRD_
