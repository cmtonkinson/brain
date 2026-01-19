# PRD: Object Storage via MinIO
## Durable Blob Storage for Brain Ingestion and Artifacts

---

## 1. Overview

### Feature Name
**Object Storage (MinIO Integration)**

### Summary
Introduce **MinIO** as a local, S3-compatible object storage layer for Brain to store **raw, large, and machine-generated artifacts** ("blobs") such as web captures, documents, audio, images, and intermediate data.

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

A dedicated blob storage layer is required.

---

## 3. Goals and Non-Goals

### Goals
- Provide durable, local-first storage for large and binary artifacts
- Support content-addressed and deterministic storage patterns
- Integrate cleanly with ingestion pipelines
- Preserve Obsidian as a lightweight, human-first knowledge base
- Enable future migration to other S3-compatible backends

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
5. **Storage choices must remain portable**

---

## 5. High-Level Architecture

```
Ingestion Source (Web, File, Audio, Email)
   ↓
Normalizer / Extractor
   ↓
MinIO (Raw & Derived Blobs)
   ↓
Metadata + References → Obsidian
   ↓
Derived Indexing (Qdrant, Summaries)
```

MinIO serves as the canonical store for non-Markdown artifacts.

---

## 6. Functional Requirements

### 6.1 Object Storage Backend

- Use **MinIO** running locally via Docker
- Expose S3-compatible API
- Support multiple logical buckets

Recommended buckets:
- `brain-raw` – raw ingested artifacts
- `brain-derived` – processed artifacts (optional)
- `brain-cache` – temporary or rebuildable data

---

### 6.2 Object Addressing

Objects should be stored using:
- content hashes (e.g. SHA-256)
- or deterministic IDs derived from source + timestamp

Example key:
```
brain-raw/web/sha256/ab12cd34...
```

This ensures:
- deduplication
- immutability
- reproducibility

---

### 6.3 Obsidian Integration

Obsidian notes must store:
- references to objects (bucket + key)
- metadata (mime type, size, capture time, source)
- optional human-readable summaries

Example frontmatter:

```yaml
blob:
  bucket: brain-raw
  key: web/sha256/ab12cd34
  mime: text/html
  size: 142312
```

Obsidian never stores raw blob contents.

---

### 6.4 Agent Responsibilities

The agent is responsible for:
- fetching and storing blobs
- generating and storing derived artifacts
- writing references and summaries to Obsidian
- never leaking raw blobs into the vault

---

## 7. Security and Access

- MinIO runs locally and is not publicly exposed
- Access credentials are managed via environment variables
- Only Brain services may access MinIO
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

### Authoritative Data
- MinIO buckets are **Tier 0** data
- Must be backed up regularly

### Recovery Strategy
- Restore MinIO data before rebuilding derived stores
- Re-run indexing and embedding pipelines as needed

---

## 10. Risks and Mitigations

### Risk: Blob Sprawl
Mitigation:
- content-addressed storage
- clear bucket boundaries
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

- [ ] MinIO deployed via Docker
- [ ] Buckets created and documented
- [ ] Agent can store and retrieve blobs
- [ ] Obsidian notes reference blobs correctly
- [ ] Backup plan documented

---

## 13. Alignment with Brain Manifesto

- **Sovereignty First:** local object storage
- **Truth Is Explicit:** raw artifacts preserved
- **Memory Is Curated:** blobs are not memory
- **Everything Compounds:** ingestion pipelines scale cleanly

---

_End of PRD_
