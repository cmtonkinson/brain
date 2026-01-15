# PRD: Universal Ingestion Pipeline
## Flexible “Ingest Anything” Pipeline for Brain OS

---

## 1. Overview

### Feature Name
**Universal Ingestion Pipeline**

### Summary
Design and implement a **flexible, extensible ingestion pipeline** capable of accepting *any input* (URLs, files, audio, text, messages, screenshots, APIs) and deterministically transforming it into:

1. durable raw storage (blob)
2. extracted / normalized text
3. structured metadata
4. embeddings for semantic search
5. optional summaries and derivatives

The pipeline establishes a **single canonical path** for all inbound information entering Brain OS.

---

## 2. Problem Statement

Without a unified ingestion pipeline, systems accumulate:
- bespoke one-off ingestion logic
- inconsistent metadata
- duplicated storage
- unclear authority boundaries
- fragile downstream assumptions

Brain OS must support *many input types* while guaranteeing:
- consistency
- rebuildability
- provenance
- separation of concerns

The ingestion pipeline is the foundation that enables everything else: memory, search, skills, and automation.

---

## 3. Goals and Non-Goals

### Goals
- Support ingestion of arbitrary content types
- Enforce a deterministic, multi-stage ingestion flow
- Separate raw data from derived artifacts
- Enable replay and reprocessing
- Make ingestion observable and auditable
- Keep Obsidian human-first and lightweight

### Non-Goals
- Real-time streaming ingestion (initially)
- Complex ETL transformations beyond extraction/normalization
- Full document management UI
- Automatic memory promotion (handled separately by Letta)

---

## 4. Design Principles

1. **Everything enters the system through ingestion**
2. **Raw artifacts are preserved**
3. **Derived artifacts are disposable**
4. **Metadata is the spine**
5. **Humans read Markdown, machines read structure**

---

## 5. Canonical Ingestion Stages

### Stage 0: Intake
Accepts inbound content from:
- URLs
- file uploads
- messages (Signal, WebUI)
- scheduled jobs
- APIs

Produces an **ingestion request** with minimal assumptions.

---

### Stage 1: Blob Storage (Authoritative)
- Store raw input in MinIO
- Never modify raw content
- Assign deterministic object key

Outputs:
- blob reference (bucket + key)
- size, mime type
- checksum

---

### Stage 2: Extraction
- Extract text or structure where possible
- Preserve original ordering
- Record extraction method and confidence

Examples:
- HTML → main article text
- PDF → text + page markers
- Audio → transcript
- Image → OCR (optional)

Outputs:
- extracted text artifact (stored as blob)
- extraction metadata

---

### Stage 3: Normalization
- Convert extracted text into normalized Markdown or plain text
- Apply minimal structural heuristics (headings, lists)
- Strip noise (ads, nav, boilerplate)

Outputs:
- normalized text artifact (blob)
- normalization metadata

---

### Stage 4: Metadata Anchoring (Obsidian)
- Create or update an Obsidian note that references:
  - raw blob
  - extracted blob
  - normalized blob
- Store:
  - source
  - timestamps
  - mime type
  - extraction confidence
  - tags / categories (if known)

This note is the **human anchor**.

---

### Stage 5: Derived Indexing
- Generate embeddings from normalized text
- Store vectors in Qdrant
- Link vectors to the anchor note

Derived and rebuildable.

---

### Stage 6: Optional Derivatives
- Summaries
- Entity extraction
- Topic classification
- Skill-specific artifacts

All optional and discardable.

---

## 6. Data Model (Conceptual)

### Ingestion Record
```json
{
  "ingest_id": "uuid",
  "source_type": "url | file | message | api",
  "created_at": "...",
  "raw_blob": {...},
  "extracted_blob": {...},
  "normalized_blob": {...},
  "anchor_note": "path/to/note.md",
  "status": "complete"
}
```

Stored in Postgres as Tier 1 system state.

---

## 7. Failure Handling

- Partial failures must be recorded
- Pipeline stages are restartable
- Failed stages may be retried independently
- Raw blob is never discarded

---

## 8. Observability

For each ingestion:
- timestamps per stage
- tools used
- errors and warnings
- size deltas
- extraction confidence

Supports debugging and pipeline improvement.

---

## 9. Security and Safety

- Raw blobs never exposed to UI directly
- Extraction tools sandboxed
- Large or untrusted content flagged
- No automatic action taken based solely on ingestion

---

## 10. Extensibility

Pipeline must allow:
- new extractors
- new normalizers
- new derivative generators
- skill-specific post-processing

Without modifying core stages.

---

## 11. Success Metrics

- All inbound content uses the same pipeline
- Vault remains small and readable
- Derived stores can be rebuilt without loss
- Debugging ingestion failures is straightforward

---

## 12. Definition of Done

- [ ] MinIO integration for raw artifacts
- [ ] Extract/normalize pipeline implemented
- [ ] Obsidian anchor notes created
- [ ] Embeddings generated from normalized text
- [ ] Ingestion records persisted
- [ ] Observability and logging in place

---

## 13. Alignment with Brain OS Manifesto

- **Truth Is Explicit:** provenance and stages recorded
- **Memory Is Curated:** ingestion ≠ memory
- **Sovereignty First:** raw artifacts preserved locally
- **Everything Compounds:** ingestion enables all downstream leverage

---

_End of PRD_
