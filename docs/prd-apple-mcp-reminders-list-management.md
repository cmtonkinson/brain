# PRD: Reminders List Management via apple-mcp
## List/Add/Delete/Rename Reminder Lists for Brain OS

---

## 1. Overview

### Feature Name
**Reminders List Management (apple-mcp)**

### Summary
Extend the existing Apple Reminders integration (via `apple-mcp` / EventKit MCP server) to support **Reminder List management** operations:

- list reminder lists
- create reminder lists
- delete reminder lists
- rename reminder lists

This enables Brain OS to manage organizational structure in Apple Reminders, not just individual reminders.

---

## 2. Problem Statement

Brain OS can create and update reminders, but without list management it cannot:

- organize reminders into project-based lists
- maintain consistent list taxonomy over time
- reconcile user intent (“put this in my ‘Work’ list”) when lists change
- support skills like weekly reviews, commitment tracking, and routing by list

Users need the agent to treat lists as first-class objects.

---

## 3. Goals and Non-Goals

### Goals
- Enable list CRUD operations for Apple Reminders
- Provide stable identifiers for lists to avoid ambiguity
- Support safe deletion semantics (explicit confirmation)
- Integrate with Policy Engine and Attention Router

### Non-Goals
- Managing list sharing/collaboration
- Managing Smart Lists or non-standard list types (initially)
- Advanced list properties beyond name and identity
- Full Reminders UI replication

---

## 4. Design Principles

1. **Lists are stable containers**
2. **Names are not identities**
3. **Deletion is dangerous**
4. **Agent must prefer reuse over proliferation**
5. **All writes are policy-gated**

---

## 5. Functional Requirements

### 5.1 List Reminder Lists

#### Description
Return all available reminder lists with stable identifiers.

#### Requirements
- Return:
  - list id (stable)
  - list name
  - optional metadata (color, type) if available
- Support filtering by name prefix (optional)

#### API (Conceptual)
```json
{
  "action": "reminders.lists.list",
  "result": [
    { "id": "abc123", "name": "Work" },
    { "id": "def456", "name": "Personal" }
  ]
}
```

---

### 5.2 Create Reminder List

#### Description
Create a new reminder list.

#### Requirements
- Input: list name
- Return: new list id
- Must reject duplicates by default (or require explicit override)
- Must be policy gated (write action)

#### API (Conceptual)
```json
{
  "action": "reminders.lists.create",
  "name": "Brain OS"
}
```

---

### 5.3 Rename Reminder List

#### Description
Rename an existing reminder list.

#### Requirements
- Input: list id + new name
- Must verify list exists
- Must log rename event
- Policy gated

#### API (Conceptual)
```json
{
  "action": "reminders.lists.rename",
  "id": "abc123",
  "new_name": "Work (HQ)"
}
```

---

### 5.4 Delete Reminder List

#### Description
Delete an existing reminder list.

#### Requirements
- Input: list id
- Must require explicit confirmation (L1 or higher)
- Must warn about reminders contained (count if possible)
- Must log deletion event

#### API (Conceptual)
```json
{
  "action": "reminders.lists.delete",
  "id": "abc123",
  "confirm": true
}
```

---

## 6. Policy & Autonomy

- **List**: allowed at L2 (read-only)
- **Create/Rename**: default L1 (approval required)
- **Delete**: L1 mandatory (approval required, cannot be L2 by default)

Scheduled jobs cannot delete lists.

---

## 7. Error Handling

Must handle:
- list not found
- duplicate name conflicts
- permission denied (macOS privacy/entitlements)
- API failures from EventKit

Errors must be explicit and surfaced to the agent.

---

## 8. Observability & Audit

Log each operation:
- actor context (Signal/WebUI/scheduled)
- action type
- list id + name
- outcome (success/failure)
- timestamp

Optional:
- write a short audit note in Obsidian for destructive actions

---

## 9. Success Metrics

- Agent can reliably target lists by ID, not name
- Reduced “which list did you mean?” ambiguity
- Supports workflows that create lists per project/initiative
- No accidental deletion events

---

## 10. Definition of Done

- [ ] MCP server supports list CRUD operations
- [ ] Stable list IDs returned and used
- [ ] Policy gating implemented for writes
- [ ] Delete requires explicit confirmation
- [ ] Logging and audit events recorded
- [ ] Integrated with Brain OS tool schema

---

_End of PRD_
