# PRD: Universal Ingestion Pipeline
## Flexible “Ingest Anything” Pipeline for Brain

---

## 1. Overview

### Feature Name
**Universal Ingestion Pipeline**

### Summary
Design and implement a **flexible, extensible ingestion pipeline** capable of accepting *any input* (URLs, files, audio, text, messages, screenshots, APIs) and deterministically transforming it into:

1. durable raw storage (blob)
2. extracted text
3. normalized Markdown
4. anchored Obsidian note
5. incremental semantic index update

The pipeline establishes a **single canonical path** for all inbound information entering Brain, with all metadata,
history, and provenance persisted in Postgres (Tier 0, authoritative).

---

## 2. Problem Statement

Without a unified ingestion pipeline, systems accumulate:
- bespoke one-off ingestion logic
- inconsistent metadata
- duplicated storage
- unclear authority boundaries
- fragile downstream assumptions

Brain must support *many input types* while guaranteeing:
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
- Automatic summarization of ingested content

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

### Stage 1: Store (Raw Blob)
- Store raw input in the local object store (durable)
- Never modify raw content
- Assign deterministic object key

Outputs:
- object key
- size, mime type
- checksum
- object metadata persisted in Postgres (UTC timestamps)
- Stage 1 dedupe: if the object already exists, mark the stage as skipped and end the ingestion

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
- Provenance record created for the normalized blob only (for now)

---

### Stage 4: Anchor (Obsidian)
- Create an Obsidian note containing the normalized Markdown
- The normalized blob remains immutable in object storage for audit/diff
- Store:
  - source
  - timestamps
  - mime type
  - extraction confidence
  - tags / categories (if known)

This note is the **human anchor** and may be edited by the operator without mutating the blob.

---

### Stage 5: Derived Indexing (Triggered by Anchor)
- Trigger an incremental indexer update after anchoring
- Generate embeddings from normalized text
- Store vectors in Qdrant

Derived and rebuildable.

---

### Stage 6: Optional Derivatives
- Summaries
- Entity extraction
- Topic classification
- Skill-specific artifacts

All optional and discardable.

---

## 6. Data Model (Normalized, Postgres)

All ingestion metadata is stored in Postgres (Tier 0). JSON/JSONB columns are not used.

### `ingestions` (per attempt)
- `id` UUID PK
- `object_key` text NOT NULL
- `source_type` text NOT NULL
- `source_uri` text NULL
- `source_actor` text NULL
- `created_at` timestamptz NOT NULL (UTC)
- `status` text NOT NULL (`queued|running|complete|failed`)
- `last_error` text NULL

### `ingestion_stage_runs`
- `id` UUID PK
- `ingestion_id` UUID NOT NULL FK → `ingestions.id`
- `stage` text NOT NULL (`store|extract|normalize|anchor`)
- `started_at` timestamptz NOT NULL (UTC)
- `finished_at` timestamptz NULL
- `status` text NOT NULL (`success|failed|skipped`)
- `error` text NULL
- `object_key` text NOT NULL
- `input_object_key` text NULL
- `output_object_key` text NULL

### `object_metadata`
- `object_key` text PK
- `created_at` timestamptz NOT NULL (UTC)
- `size_bytes` bigint NOT NULL
- `mime_type` text NULL
- `checksum` text NOT NULL
- `first_ingested_at` timestamptz NOT NULL (UTC)
- `last_ingested_at` timestamptz NOT NULL (UTC)

### `provenance_records` (normalized artifacts only)
- `id` UUID PK
- `object_key` text NOT NULL UNIQUE FK → `object_metadata.object_key`
- `created_at` timestamptz NOT NULL (UTC)
- `updated_at` timestamptz NOT NULL (UTC)

### `provenance_sources` (normalized, deduped)
- `id` UUID PK
- `provenance_id` UUID NOT NULL FK → `provenance_records.id`
- `ingestion_id` UUID NOT NULL FK → `ingestions.id`
- `source_type` text NOT NULL
- `source_uri` text NULL
- `source_actor` text NULL
- `captured_at` timestamptz NOT NULL (UTC)

Uniqueness constraint to avoid duplicate sources, for example:
`UNIQUE (provenance_id, source_type, source_uri, source_actor)`

---

## 7. Execution Model

- All ingestion stages run asynchronously via the existing Postgres-backed job scheduler
- Each stage is idempotent
- Dedupe halts after Stage 1 (Store); Stage 1 is marked `skipped` and the ingestion is `complete`

---

## 8. Failure Handling

- Partial failures must be recorded
- Pipeline stages are restartable
- Failed stages may be retried independently
- Raw blob is never discarded

---

## 9. Observability

All metrics, traces, and logs flow through OpenTelemetry (OTEL).

For each ingestion, persist in Postgres:
- timestamps per stage
- errors and warnings
- stage outcomes

Supports debugging and pipeline improvement.

---

## 10. Security and Safety

- Raw blobs never exposed to UI directly
- Extraction tools sandboxed
- Large or untrusted content flagged
- No automatic action taken based solely on ingestion

---

## 11. Extensibility

Pipeline must allow:
- new extractors
- new normalizers
- new derivative generators
- skill-specific post-processing

Without modifying core stages.

---

## 12. Success Metrics

- All inbound content uses the same pipeline
- Vault remains small and readable
- Derived stores can be rebuilt without loss
- Debugging ingestion failures is straightforward

---

## 13. Definition of Done

- [ ] Object store integration for raw artifacts
- [ ] Extract/normalize pipeline implemented
- [ ] Obsidian anchor notes created
- [ ] Embeddings generated from normalized text
- [ ] Ingestion records persisted (Postgres, Tier 0)
- [ ] Observability and logging in place via OTEL

---

## 13. Alignment with Brain Manifesto

- **Truth Is Explicit:** provenance and stages recorded
- **Memory Is Curated:** ingestion ≠ memory
- **Sovereignty First:** raw artifacts preserved locally
- **Everything Compounds:** ingestion enables all downstream leverage

---

_End of PRD_
