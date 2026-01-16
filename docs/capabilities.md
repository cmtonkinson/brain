# Brain OS Capability Vocabulary

This document defines the canonical capability vocabulary and governance rules for Brain OS.
Capabilities are stable, composable permission labels that bound what a skill may do.

## Vocabulary (v1.0.0)

### Memory + Knowledge
- `obsidian.read` - Read notes from the canonical Obsidian vault.
- `obsidian.write` - Create or append notes in the canonical vault.
- `memory.propose` - Propose durable memory without committing it.
- `memory.promote` - Commit durable memory (privileged).
- `vault.search` - Search the vault (semantic or lexical).

### Messaging + Attention
- `messaging.read` - Read inbound messages.
- `messaging.send` - Send outbound messages.
- `attention.notify` - Deliver a user-visible notification.

### Calendar + Reminders
- `calendar.read` - Read calendar data.
- `calendar.write` - Create or update calendar data.
- `reminders.read` - Read reminders.
- `reminders.write` - Create or update reminders.

### Ingestion + Storage
- `blob.store` - Store raw artifacts (HTML, PDFs, audio).
- `blob.read` - Read stored artifacts.
- `ingest.normalize` - Normalize raw content to structured text.

### File System / Host Ops
- `filesystem.read` - Read local filesystem content.
- `filesystem.write` - Write local filesystem content.

### External APIs
- `github.read` - Read GitHub data.
- `github.write` - Write or mutate GitHub data.
- `web.fetch` - Fetch external web content.

### System Operations
- `scheduler.read` - Read scheduler/job state.
- `scheduler.write` - Create or update scheduler/job state.
- `policy.read` - Read policy configuration and rules.
- `policy.write` - Update policy configuration and rules.

### Observability
- `telemetry.emit` - Emit metrics, logs, or traces.

## Governance Rules

### Naming
- Capabilities use the form `domain.verb`.
- Domains are stable nouns (e.g., `obsidian`, `calendar`, `filesystem`).
- Verbs are consistent across domains: `read`, `write`, `send`, `notify`, `fetch`, `store`, `promote`.
- Avoid overlaps: a capability must describe a single, bounded authority.

### Semver-like Stability Guarantees
- Capability IDs are immutable once released.
- Meaning cannot change in a breaking way without creating a new ID.
- Removing a capability requires deprecation first; IDs are never reused.
- The vocabulary version increments:
  - Major: breaking change to meanings or governance policy.
  - Minor: additive new capabilities.
  - Patch: description or documentation clarifications.

### Additions
- Additions must be justified by a concrete skill or policy need.
- New capabilities must be minimal and composable.
- Capabilities should prefer `read`/`write` split over a single broad label.

### Renames and Deprecations
- Renames are expressed as: new ID + deprecate old ID.
- Deprecated IDs remain valid for at least one minor version.
- Deprecation notices must include a migration note and replacement ID.

### Ownership and Review
- Owners: `core` (platform maintainers) and `security` (policy review).
- Required reviews:
  - `core` approval for any change.
  - `security` approval for any capability that introduces side effects.

### Source of Truth
- `docs/capabilities.md` is the human-readable authority.
- `config/capabilities.json` is the machine-readable authority.
- Validation tooling must consume `config/capabilities.json`.
