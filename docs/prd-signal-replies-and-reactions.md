# PRD: Signal Replies & Reactions
## Low-Noise, Threaded Acknowledgement for Brain OS

---

## 1. Overview

### Feature Name
**Signal Replies & Reactions**

### Summary
Enable Brain OS to **reply to specific Signal messages** (via quoted replies) and **react to messages with emojis** (👍, ✅, ⏳, etc.) using `signal-cli`, exposed through the existing HTTP wrapper and agent tooling.

This feature enables **low-noise, high-trust communication** by allowing the system to acknowledge, update, and complete requests *in context*, without unnecessary interruption.

---

## 2. Problem Statement

Current agent-to-user communication via messaging suffers from:

- Excessive verbosity for simple acknowledgements
- Loss of conversational context in delayed responses
- Cognitive noise caused by redundant or out-of-band messages

Users need:
- Clear confirmation that a message was received
- Lightweight status signaling during async or scheduled work
- Responses that stay visually tied to the original request

---

## 3. Goals and Non-Goals

### Goals
- Allow Brain OS to **reply to specific Signal messages**
- Allow Brain OS to **react to specific Signal messages**
- Preserve conversational locality via quoted replies
- Reduce message volume via emoji-based acknowledgements
- Support delayed and scheduled replies (hours or days later)
- Align with *Attention Is Sacred* and *Bounded Action* principles

### Non-Goals
- Full Signal client reimplementation
- Multi-emoji reaction management (add/remove/replace)
- Message editing or deletion
- Group moderation or admin actions

---

## 4. User Stories

### Primary User Stories

1. **Acknowledgement**
   > As a user, when I send Brain a request, I want a quick 👍 reaction so I know it was received.

2. **Async Processing**
   > As a user, when Brain is working on something long-running, I want a ⏳ reaction instead of repeated status messages.

3. **Completion**
   > As a user, I want Brain to reply directly to my original message when the task is finished.

4. **Scheduled Follow-Up**
   > As a user, if I ask Brain to remind me later, I want the reminder to reply to my original message, not arrive out of context.

---

## 5. Functional Requirements

### 5.1 Reply to Message (Quoted Reply)

#### Description
Brain OS can send a message that explicitly quotes a prior Signal message, creating a visible “reply” in the Signal UI.

#### Requirements
- Must reference:
  - Original message author
  - Original message timestamp
  - Optional quoted text
- Must work for:
  - Direct messages
  - Group messages
- Must support delayed execution (scheduler-driven)

---

### 5.2 React to Message

#### Description
Brain OS can react to a specific Signal message using a single emoji.

#### Requirements
- Must support standard emoji (👍 ❤️ 😂 👀 ⏳ ✅ ❌)
- Must target a specific message via author + timestamp
- Must work without sending a text message
- Must be idempotent (repeating the same reaction is safe)

---

## 6. UX & Interaction Design

### Reaction Semantics (Recommended Convention)

| Emoji | Meaning |
|------|--------|
| 👍 | Received / acknowledged |
| 👀 | Reading / processing |
| ⏳ | Deferred / scheduled |
| ✅ | Completed successfully |
| ❌ | Cannot comply / failed |
| ⚠️ | Needs clarification |

---

## 7. Technical Design

### Dependencies
- signal-cli (modern version with reaction support)
- Existing Signal HTTP wrapper
- Persistent message metadata store (Postgres)

---

## 8. Observability & Auditing

Each reply or reaction must be logged with:
- timestamp
- action type (reply/react)
- target message reference
- initiating actor
- success/failure status

---

## 9. Definition of Done

- Agent can reply to a Signal message in-thread
- Agent can react to a Signal message
- Metadata persistence implemented
- Scheduler can trigger delayed replies
- Logging and error handling in place

---

_End of PRD_
