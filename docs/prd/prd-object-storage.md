# PRD: Local Object Storage
## Durable Blob Storage for Brain Ingestion and Artifacts

---

## 1. Overview

### Feature Name
**Object Storage (Local Filesystem)**

### Summary
Introduce a **minimal, local, content-addressed object store** for Brain to store **raw, large, and machine-generated artifacts** ("blobs") such as web captures, documents, audio, images, and intermediate data.

This establishes a clean separation between:
- **Authoritative human knowledge** (Obsidian Markdown)
- **Durable raw artifacts** (object storage)
- **Derived or cached data** (embeddings, summaries)

---

## 2. Problem Statement

Brain must ingest and process data that does not belong in a Markdown-based knowledge system:

- raw HTML from web clipping
- PDFs and documents
- audio recordings and transcriptions
- screenshots and images
- intermediate or derived machine artifacts

Obsidian is not designed to be a blob store:
- binary files bloat vaults
- frequent writes cause sync and diff issues
- large artifacts reduce usability and portability

A dedicated blob storage layer is required, but it should be **minimal, local, and dependency-light**.

---

## 3. Goals and Non-Goals

### Goals
- Provide durable, local-first storage for large and binary artifacts
- Support content-addressed, deterministic storage patterns
- Integrate cleanly with ingestion pipelines
- Preserve Obsidian as a lightweight, human-first knowledge base
- Avoid heavyweight object-store dependencies

### Non-Goals
- Acting as a primary user-facing file browser
- Replacing Obsidian attachments for small, human-authored files
- Public or multi-tenant object hosting
- Complex lifecycle automation in the initial phase

---

## 4. Design Principles

1. **Obsidian stores meaning, not mass**
2. **Blobs are referenced, never embedded**
3. **Raw artifacts are preserved**
4. **Derived data is always rebuildable**
5. **Storage must remain local and inspectable**

---

## 5. High-Level Architecture

```
Ingestion Source (Web, File, Audio, Email)
   ↓
Normalizer / Extractor
   ↓
Local Object Store (raw & derived blobs)
   ↓
Metadata + References → Obsidian
   ↓
Derived Indexing (Qdrant, Summaries)
```

The local object store serves as the canonical store for non-Markdown artifacts.

---

## 6. Functional Requirements

### 6.1 Object Storage Backend

- Provide a minimal, Python-backed object store
- Store objects on the local filesystem under a configurable root directory (`objects.root_dir`)
- Avoid any external object-store dependencies (no MinIO, no S3)

### 6.2 Object Addressing

Objects must be stored using content hashing with deterministic keys:

- **Object key format:** `b1:sha256:<hexdigest>`
- **Digest input:** `"b1:\0" + content bytes`
- **Filesystem layout:**
  - Use the first two digest bytes as the first subdirectory
  - Use the next two digest bytes as the second subdirectory
  - Store the object as a file named `<hexdigest>`

Example:
```
object_key: b1:sha256:abcdef...
path: <root>/ab/cd/abcdef...
```

This ensures:
- deduplication
- immutability
- reproducibility

### 6.3 Object Store API

Public API surface (Python):
- `write(object) -> object_key`
- `read(object_key) -> object`
- `delete(object_key) -> bool`

Semantics:
- `write` and `delete` are **idempotent**
- if the object exists, `write` returns the existing key without rewriting
- `delete` returns `True` whether or not the object exists

### 6.4 Obsidian Integration

Obsidian notes must store:
- references to objects (object key)
- metadata (mime type, size, capture time, source)
- optional human-readable summaries

Example frontmatter:

```yaml
blob:
  object_key: b1:sha256:ab12cd34...
  mime: text/html
  size: 142312
```

Obsidian never stores raw blob contents.

### 6.5 Agent Responsibilities

The agent is responsible for:
- fetching and storing blobs
- generating and storing derived artifacts
- writing references and summaries to Obsidian
- never leaking raw blobs into the vault

---

## 7. Security and Access

- Object store resides on local disk and is not exposed over the network
- Only Brain services may access object storage directly
- UI clients never access object storage directly

---

## 8. Observability

The system must log:
- object creation events
- source and ingestion context
- storage failures
- size and growth metrics

Optional:
- periodic reports on storage usage
- orphaned object detection

---

## 9. Backup and Recovery

### Data Classification
- Object store data is **Tier 1** system state
- Backup is **recommended** but not required to restore Tier 0 authority

### Recovery Strategy
- Restore object store data before rebuilding derived stores when available
- Re-run indexing and embedding pipelines as needed

---

## 10. Risks and Mitigations

### Risk: Blob Sprawl
Mitigation:
- content-addressed storage
- clear storage layout
- optional lifecycle policies later

### Risk: Vault Coupling
Mitigation:
- references only
- no binary embedding in Markdown

---

## 11. Success Metrics

- Vault remains small and fast
- Large artifacts are durable and inspectable
- Ingestion pipelines are simplified
- Derived data can be safely discarded and rebuilt

---

## 12. Definition of Done

- [ ] Local object store implemented
- [ ] Agent can store and retrieve blobs
- [ ] Obsidian notes reference blobs correctly
- [ ] Backup guidance documented

---

## 13. Alignment with Brain Manifesto

- **Sovereignty First:** local object storage
- **Truth Is Explicit:** raw artifacts preserved
- **Memory Is Curated:** blobs are not memory
- **Everything Compounds:** ingestion pipelines scale cleanly

---

_End of PRD_
