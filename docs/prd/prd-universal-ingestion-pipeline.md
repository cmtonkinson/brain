# PRD: Universal Ingestion Pipeline
## Flexible “Ingest Anything” Pipeline for Brain

---

## 1. Overview

### Feature Name
**Universal Ingestion Pipeline**

### Summary
Design and implement a **flexible, extensible ingestion pipeline** capable of accepting *any input* (URLs, files, audio, text, messages, screenshots, APIs) and deterministically transforming it into:

1. durable raw storage (Tier 0 blob)
2. extracted text
3. normalized Markdown
4. anchored Obsidian note (which implicitly triggers indexing)

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
- Allow Obsidian anchor notes to be edited without mutating stored blobs

### Non-Goals
- Real-time streaming ingestion (initially)
- Complex ETL transformations beyond extraction/normalization
- Full document management UI
- Automatic memory promotion (handled separately by Letta)
- Automatic summarization of ingested content
- Enforcing parity between Obsidian anchors and normalized blobs

---

## 4. Design Principles

1. **Raw artifacts are preserved (Tier 0)**
2. **Derived artifacts are disposable**
3. **Metadata is the spine**
4. **Humans read Markdown, machines read structure**
5. **Anchors are editable and may diverge from stored blobs**

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
- Store raw input in the local object store (Tier 0, durable)
- Never modify raw content
- Assign deterministic object key

Outputs:
- raw artifact object key
- size, mime type
- checksum
- artifact metadata persisted in Postgres (UTC timestamps)
- Stage 1 dedupe: if the raw artifact already exists, mark the stage as skipped and record provenance context

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
- extracted text artifacts (stored as blobs; multiple outputs supported)
- extraction metadata

---

### Stage 3: Normalization
- Convert extracted text into normalized Markdown or plain text
- Apply minimal structural heuristics (headings, lists)
- Strip noise (ads, nav, boilerplate)

Outputs:
- normalized text artifacts (blobs; multiple outputs supported)
- normalization metadata
- Provenance record created for the normalized blob

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
  - Obsidian note URI/path
- Anchoring implicitly triggers the incremental indexer update

This note is the **human anchor** and may be edited by the operator without mutating the blob or back-propagating into blob storage. Divergence between the Obsidian note and the normalized blob is expected and accepted.

---

## 6. Data Model (Normalized, Postgres)

All ingestion metadata is stored in Postgres (Tier 0). JSONB is allowed only for extractor/normalizer tool metadata.

### `ingestions` (per attempt)
- `id` UUID PK
- `source_type` text NOT NULL
- `source_uri` text NULL
- `source_actor` text NULL
- `created_at` timestamptz NOT NULL (UTC)
- `status` text NOT NULL (`queued|running|complete|failed`)
- `last_error` text NULL

### `artifacts` (all stage outputs)
- `object_key` text PK
- `created_at` timestamptz NOT NULL (UTC)
- `size_bytes` bigint NOT NULL
- `mime_type` text NULL
- `checksum` text NOT NULL
- `artifact_type` text NOT NULL (`raw|extracted|normalized`)
- `first_ingested_at` timestamptz NOT NULL (UTC)
- `last_ingested_at` timestamptz NOT NULL (UTC)
- `parent_object_key` text NULL FK → `artifacts.object_key`
- `parent_stage` text NULL (`store|extract|normalize`)
Derived artifacts must reference the prior stage output they were produced from.

### `ingestion_artifacts` (per ingestion, per stage output)
- `id` UUID PK
- `ingestion_id` UUID NOT NULL FK → `ingestions.id`
- `stage` text NOT NULL (`store|extract|normalize|anchor`)
- `object_key` text NULL FK → `artifacts.object_key`
- `created_at` timestamptz NOT NULL (UTC)
- `status` text NOT NULL (`success|failed|skipped`)
- `error` text NULL
- Uniqueness constraint: `UNIQUE (ingestion_id, stage, object_key)`
Multiple rows per stage are allowed to support attachments and fan-out (e.g., a message with several photos).

### `extraction_metadata`
- `object_key` text PK FK → `artifacts.object_key`
- `method` text NOT NULL
- `confidence` numeric NULL
- `page_count` int NULL
- `created_at` timestamptz NOT NULL (UTC)
- `tool_metadata` jsonb NULL

### `normalization_metadata`
- `object_key` text PK FK → `artifacts.object_key`
- `method` text NOT NULL
- `confidence` numeric NULL
- `created_at` timestamptz NOT NULL (UTC)
- `tool_metadata` jsonb NULL

### `anchor_notes`
- `id` UUID PK
- `normalized_object_key` text NOT NULL UNIQUE FK → `artifacts.object_key`
- `note_uri` text NOT NULL
- `note_title` text NULL
- `created_at` timestamptz NOT NULL (UTC)
- `updated_at` timestamptz NOT NULL (UTC)

### `provenance_records` (normalized artifacts only)
- `id` UUID PK
- `normalized_object_key` text NOT NULL UNIQUE FK → `artifacts.object_key`
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
- Single pipeline worker (no threading) for now, so locking is out of scope
- Dedupe is enforced at Stage 1 (Store); Stage 1 is marked `skipped` when the raw artifact already exists
- Normalization and anchoring always run from the current ingestion context (no short-circuit to anchor on duplicates)

---

## 7.1 Example: Fan-Out Ingestion (Message With Attachments)

Example: An iMessage contains text plus three photos.

Flow:
- Stage 0 Intake: 1 ingestion created
- Stage 1 Store: 4 raw artifacts (message JSON + 3 photos)
- Stage 2 Extraction:
  - 1 extracted text artifact from the message body
  - 3 OCR text artifacts (one per photo)
- Stage 3 Normalization: 4 normalized artifacts (one per extracted output)
- Stage 4 Anchor: 1 Obsidian note that embeds links/references to the 4 normalized artifacts

Schema notes:
- Each derived artifact stores `parent_object_key` pointing to its prior-stage artifact.
- `ingestion_artifacts` has multiple rows per stage, all tied to the same `ingestion_id`.

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
- Tier 0 object store remains authoritative for raw blobs
- Obsidian anchors remain editable without corrupting blob provenance

---

## 13. Definition of Done

- [ ] Object store integration for raw artifacts
- [ ] Extract/normalize pipeline implemented
- [ ] Obsidian anchor notes created
- [ ] Embeddings generated from normalized text
- [ ] Ingestion records persisted (Postgres, Tier 0)
- [ ] Observability and logging in place via OTEL

---

## 14. Alignment with Brain Manifesto

- **Truth Is Explicit:** provenance and stages recorded
- **Memory Is Curated:** ingestion ≠ memory
- **Sovereignty First:** raw artifacts preserved locally
- **Everything Compounds:** ingestion enables all downstream leverage

---

_End of PRD_
