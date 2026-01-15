# PRD: Obsidian File Rename & Delete via Agent API
## Safe, Policy-Gated Vault Refactoring for Brain OS

---

## 1. Overview

### Feature Name
**Obsidian File Rename/Delete (Agent API)**

### Summary
Extend Brain OS’s Obsidian integration (via Obsidian Local REST API) to allow the agent to:

- rename/move notes (including folder moves)
- delete notes

This enables controlled vault refactoring (cleanup, normalization, organization, archiving) while preserving safety, auditability, and Obsidian link integrity.

---

## 2. Problem Statement

Brain OS can create and update notes, but lacks the ability to manage note lifecycle and structure:

- files accumulate in wrong folders
- naming conventions drift
- duplicates remain
- refactors require manual effort
- vault structure becomes inconsistent over time

Without rename/delete capabilities, Brain OS cannot:
- enforce taxonomy
- keep ingestion anchors organized
- support large-scale cleanup and migration tasks

---

## 3. Goals and Non-Goals

### Goals
- Enable agent-driven rename/move operations
- Enable agent-driven delete operations
- Preserve link integrity where possible
- Gate all destructive operations behind policy and approvals
- Provide audit logs and optional Obsidian change journal

### Non-Goals
- Arbitrary filesystem access outside the vault
- Bulk refactors without explicit review (initially)
- Automatic deletion as part of routine workflows
- Obsidian core plugin configuration changes

---

## 4. Design Principles

1. **Vault structure is part of the knowledge system**
2. **Deletion is dangerous and rare**
3. **Moves should be reversible**
4. **Prefer archival over deletion**
5. **Always leave an audit trail**

---

## 5. Functional Requirements

### 5.1 Rename/Move File

#### Description
Rename a note and/or move it to a different folder within the vault.

#### Requirements
- Input:
  - current path
  - new path
- Must verify:
  - source exists
  - destination does not conflict (unless overwrite explicitly allowed)
- Must support folder creation if missing (optional)
- Must log changes

#### API (Conceptual)
```json
{
  "action": "obsidian.file.rename",
  "from": "Inbox/clip-2026-01-15.md",
  "to": "Sources/Web/clip-2026-01-15.md"
}
```

---

### 5.2 Delete File

#### Description
Delete a note from the vault.

#### Requirements
- Input: file path
- Must require explicit confirmation (L1 mandatory)
- Default behavior should be **archive** rather than delete, if configured:
  - move to `Trash/` or `Archive/`
- Must log deletions and rationale
- Must allow “dry-run” preview mode for bulk operations

#### API (Conceptual)
```json
{
  "action": "obsidian.file.delete",
  "path": "Inbox/temporary-note.md",
  "confirm": true
}
```

---

## 6. Link Integrity Considerations

### 6.1 Renames
Obsidian generally preserves backlinks when files are renamed inside Obsidian, but through APIs this may vary.

Requirements:
- Prefer using Obsidian-native rename endpoints if available
- If only filesystem moves are possible, agent must:
  - optionally run a link update pass
  - or create a redirect stub note at old path (optional)

### 6.2 Deletes
Deletion must consider:
- inbound links
- whether the note is an anchor for ingested artifacts

The agent should:
- warn if the note is referenced elsewhere (best effort)
- prefer archive/stub patterns over hard delete

---

## 7. Policy & Autonomy

- Rename/Move: default L1 (approval required) unless scoped to safe folders
- Delete: L1 mandatory, never automatic by default

Scheduled jobs cannot delete notes.

---

## 8. Observability & Audit

Log:
- actor context
- operation (rename/delete)
- from/to paths
- timestamp
- outcome

Optional:
- write an Obsidian “Change Log” note under `Brain/Audit/`

---

## 9. Safety UX

Before executing destructive changes, Brain OS must support:
- a preview listing proposed changes
- a single confirmation step
- reversible defaults (archive)

---

## 10. Success Metrics

- Vault structure remains consistent over time
- Reduced manual cleanup overhead
- No accidental loss of important notes
- High trust in agent-led refactors

---

## 11. Definition of Done

- [ ] Agent tool endpoints for rename/move and delete
- [ ] Policy gates integrated and enforced
- [ ] Archive-by-default option implemented
- [ ] Logging and audit records present
- [ ] Link integrity strategy documented
- [ ] Dry-run preview supported

---

_End of PRD_
