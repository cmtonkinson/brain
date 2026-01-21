# Phase 1 Implementation Plan: Core Agent with Obsidian Tools

**Document Version:** 1.0
**Created:** 2026-01-12
**Status:** Planning Complete - Ready for Implementation

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Current State Assessment](#current-state-assessment)
3. [Architecture Overview](#architecture-overview)
4. [Component Design](#component-design)
5. [File-by-File Implementation Plan](#file-by-file-implementation-plan)
6. [Data Flow Diagrams](#data-flow-diagrams)
7. [Testing Strategy](#testing-strategy)
8. [Configuration Requirements](#configuration-requirements)
9. [Rollout Plan](#rollout-plan)
10. [Continuation Notes](#continuation-notes)

---

## Executive Summary

### Goal
Implement a functional Pydantic AI agent that can:
1. Receive messages (initially via CLI test mode, then Signal)
2. Search the Obsidian knowledge base
3. Create and modify notes in Obsidian
4. Respond intelligently using Claude via LiteLLM
5. Log conversations to Obsidian for persistence

### Scope
This phase focuses on **text-based interaction** only. Voice (Phase 2), phone (Phase 3), and SMS (Phase 4) are out of scope.

### Key Deliverables
- Working Pydantic AI agent with tool calling
- Obsidian tools (search, read, create, append)
- Signal message polling and response
- Conversation logging to Obsidian
- CLI test mode for development

---

## Current State Assessment

### Implemented (Ready to Use)

| Component | File | Status |
|-----------|------|--------|
| Configuration | `src/config.py` | Complete - Pydantic Settings with all env vars |
| Database Models | `src/models.py` | Complete - SQLAlchemy ORM + Pydantic schemas |
| LLM Client | `src/llm.py` | Complete - LiteLLM wrapper (async + sync) |
| Obsidian HTTP Client | `src/tools/obsidian.py` | Complete - All REST API methods |
| Docker Services | `docker-compose.yml` | Complete - All services defined |

### Stubbed Out (Needs Implementation)

| Component | File | Current State |
|-----------|------|---------------|
| Agent Core | `src/agent.py` | Empty loop with TODOs |
| Tool Definitions | `src/tools/*.py` | HTTP client exists, no Pydantic AI tools |
| Signal Handler | (none) | Not implemented |
| Indexer | `src/indexer.py` | File discovery only, no embedding pipeline |

### Dependencies Already Installed

From `pyproject.toml`:
- `pydantic-ai>=0.0.14` - Agent framework
- `litellm^1.50.0` - LLM abstraction
- `qdrant-client^1.11.0` - Vector database (for future RAG)
- `httpx^0.27.0` - Async HTTP
- `sqlalchemy^2.0.0` - Database ORM
- `redis^5.0.0` - Task queue (future)

---

## Architecture Overview

### Design Principles

1. **Pydantic AI as orchestrator**: The agent manages tool selection and conversation flow
2. **Obsidian as canonical store**: All conversations and knowledge persist in markdown
3. **PostgreSQL for operational state**: Tasks, action logs, and metadata
4. **Stateless agent**: Agent can restart without losing context (persisted externally)

### High-Level Flow

```
Signal Message → Agent → Tool Selection → Execute Tool → Response → Signal Reply
                  ↓
            Log to Obsidian
            Log to PostgreSQL
```

### Component Relationships

```
┌─────────────────────────────────────────────────────────────────┐
│                        src/agent.py                              │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────────┐ │
│  │ BrainAgent  │──│ Pydantic AI  │──│ LiteLLM (Claude)        │ │
│  │  (main)     │  │   Agent      │  │                         │ │
│  └─────────────┘  └──────────────┘  └─────────────────────────┘ │
│         │                │                                       │
│         │         ┌──────┴──────┐                               │
│         │         │   Tools     │                               │
│         │         └──────┬──────┘                               │
└─────────│────────────────│──────────────────────────────────────┘
          │                │
          ▼                ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ src/tools/      │  │ src/tools/      │  │ src/services/   │
│ obsidian.py     │  │ memory.py       │  │ signal.py       │
│                 │  │ (conversation)  │  │                 │
│ - search_notes  │  │ - get_context   │  │ - poll_messages │
│ - read_note     │  │ - log_message   │  │ - send_reply    │
│ - create_note   │  │                 │  │                 │
│ - append_note   │  │                 │  │                 │
└────────┬────────┘  └────────┬────────┘  └────────┬────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ Obsidian        │  │ PostgreSQL      │  │ Signal API      │
│ REST API        │  │                 │  │ (Docker)        │
│ :27123          │  │ :5432           │  │ :8080           │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

---

## Component Design

### 1. Pydantic AI Agent (`src/agent.py`)

#### Agent Definition

The agent needs:
- **System prompt**: Defines personality, capabilities, and constraints
- **Tools**: Functions the agent can call
- **Model**: Claude via LiteLLM
- **Dependencies**: Injected context (user info, settings)

#### System Prompt Design

```
You are Brain, a personal AI assistant for {user}. You have access to their
Obsidian knowledge base and can help with:
- Searching and retrieving information from notes
- Creating new notes and capturing ideas
- Answering questions based on stored knowledge
- Managing tasks and reminders

Guidelines:
- Be concise but thorough
- When searching notes, summarize relevant findings
- Always confirm before creating or modifying notes
- If you don't find information, say so clearly
```

#### Dependency Injection

Pydantic AI uses a `deps` parameter for runtime context:

```python
@dataclass
class AgentDeps:
    user: str
    obsidian: ObsidianClient
    db_session: AsyncSession
    signal_sender: str | None = None  # For reply routing
```

### 2. Obsidian Tools (`src/tools/obsidian.py`)

#### Tool Definitions

Each tool needs:
- Clear docstring (used by LLM to understand when to call)
- Type hints for parameters
- Return type annotation
- Error handling

**Tool: search_notes**
- Purpose: Find notes matching a query
- Parameters: `query: str`, `limit: int = 10`
- Returns: List of note paths with snippets
- LLM guidance: "Search when user asks about topics, people, or concepts"

**Tool: read_note**
- Purpose: Get full content of a specific note
- Parameters: `path: str`
- Returns: Note content as string
- LLM guidance: "Read after search to get full context"

**Tool: create_note**
- Purpose: Create a new note in the vault
- Parameters: `path: str`, `content: str`
- Returns: Confirmation with created path
- LLM guidance: "Create for new topics, meeting notes, ideas"

**Tool: append_to_note**
- Purpose: Add content to existing note
- Parameters: `path: str`, `content: str`
- Returns: Confirmation
- LLM guidance: "Append for adding to journals, logs, or ongoing notes"

### 3. Signal Integration (`src/services/signal.py`)

#### Message Polling

The signal-cli-rest-api exposes:
- `GET /v1/receive/{number}` - Poll for new messages
- `POST /v2/send` - Send a message

#### Polling Strategy

```python
async def poll_messages(phone_number: str) -> list[SignalMessage]:
    """Poll Signal API for new messages."""
    # GET /v1/receive/{number}
    # Returns array of message envelopes
    # Filter for dataMessage (ignore receipts, typing indicators)
```

#### Response Flow

```python
async def send_reply(phone_number: str, recipient: str, message: str) -> None:
    """Send reply via Signal."""
    # POST /v2/send
    # Body: {"message": str, "number": str, "recipients": [str]}
```

### 4. Conversation Memory (`src/tools/memory.py`)

#### Design Decision: Obsidian-First

Conversations are stored as Obsidian notes, not in PostgreSQL. This ensures:
- Human-readable conversation history
- Searchable via Obsidian/Smart Connections
- Portable and backup-friendly

#### Conversation Note Structure

```markdown
---
type: conversation
channel: signal
started: 2026-01-12T10:30:00
participants:
  - +15551234567
tags:
  - conversation
  - brain
---

# Conversation: 2026-01-12

## 10:30 - User
What meetings do I have today?

## 10:30 - Brain
Based on your calendar, you have:
- 11:00 AM: Team standup
- 2:00 PM: 1:1 with Sarah
...
```

#### Conversation Path Convention

`Brain/Conversations/YYYY/MM/signal-{date}-{short-hash}.md`

Example: `Brain/Conversations/2026/01/signal-2026-01-12-a3f2.md`

### 5. Action Logging (`src/services/logging.py`)

#### PostgreSQL Action Log

Every agent action is logged to `action_logs` table:
- `action_type`: "search", "create_note", "send_message", etc.
- `description`: Human-readable description
- `result`: JSON blob with details
- `timestamp`: When it occurred

#### Purpose

- Debugging and observability
- Audit trail for sensitive actions
- Future: Archive to Obsidian weekly

---

## File-by-File Implementation Plan

### Files to Modify

#### 1. `src/agent.py` - Complete Rewrite

**Current:** Empty async loop
**Target:** Full Pydantic AI agent with message handling

**Implementation Steps:**
1. Define `AgentDeps` dataclass for dependency injection
2. Create Pydantic AI `Agent` instance with system prompt
3. Register all tools with `@agent.tool` decorator
4. Implement `process_message(message: str, deps: AgentDeps) -> str`
5. Implement `main()` with:
   - Database session initialization
   - Signal polling loop
   - Message processing pipeline
6. Add CLI argument parsing for `--test` mode

**Key Functions:**
- `create_agent() -> Agent` - Factory function for agent
- `process_message(message, deps) -> str` - Core message handler
- `handle_signal_message(envelope, deps)` - Signal-specific wrapper
- `main()` - Entry point with loop

#### 2. `src/tools/obsidian.py` - Add Tool Decorators

**Current:** HTTP client class
**Target:** HTTP client + Pydantic AI tool functions

**Implementation Steps:**
1. Keep existing `ObsidianClient` class
2. Add module-level tool functions that wrap client methods
3. Each tool function should:
   - Accept `RunContext[AgentDeps]` as first param (Pydantic AI convention)
   - Have comprehensive docstring for LLM
   - Handle errors gracefully with user-friendly messages

**New Functions:**
- `search_notes(ctx, query, limit=10) -> str`
- `read_note(ctx, path) -> str`
- `create_note(ctx, path, content) -> str`
- `append_to_note(ctx, path, content) -> str`

### Files to Create

#### 3. `src/services/signal.py` - New File

**Purpose:** Signal message polling and sending

**Implementation Steps:**
1. Create `SignalClient` class with httpx
2. Implement `poll_messages(phone_number)` method
3. Implement `send_message(phone_number, recipient, text)` method
4. Add proper error handling for API failures
5. Parse message envelopes to extract text content

**Class Structure:**
```python
class SignalClient:
    def __init__(self, api_url: str)
    async def poll_messages(self, phone_number: str) -> list[dict]
    async def send_message(self, from_number: str, to_number: str, message: str) -> None
    async def get_contacts(self, phone_number: str) -> list[dict]
```

#### 4. `src/tools/memory.py` - New File

**Purpose:** Conversation persistence and retrieval

**Implementation Steps:**
1. Define conversation note path generator
2. Implement `get_or_create_conversation(deps, sender)` function
3. Implement `log_message(deps, sender, role, content)` function
4. Format messages as markdown with timestamps
5. Use Obsidian client for persistence

**Key Functions:**
- `get_conversation_path(date, sender) -> str`
- `log_message(deps, role, content) -> None`
- `get_recent_context(deps, sender, n=10) -> str`

#### 5. `src/services/database.py` - New File

**Purpose:** Database session management and action logging

**Implementation Steps:**
1. Create async SQLAlchemy engine and session factory
2. Implement `get_session()` context manager
3. Implement `log_action(session, action_type, description, result)`
4. Add table creation on startup

**Key Functions:**
- `init_db() -> None` - Create tables if not exist
- `get_session() -> AsyncSession` - Session factory
- `log_action(session, type, desc, result) -> None`

#### 6. `src/tools/__init__.py` - Update

**Current:** Empty
**Target:** Export all tool functions for agent registration

**Content:**
- Import and re-export all tool functions
- Provide `get_all_tools()` helper for agent setup

### Files to Update

#### 7. `src/models.py` - Minor Updates

**Add:**
- `ConversationMessage` Pydantic model for in-memory message passing
- Update `SignalMessage` with additional fields from API

#### 8. `src/config.py` - Minor Updates

**Add:**
- `signal.phone_number: str` - The registered phone number for the agent
- `conversation.folder: str = "Brain/Conversations"` - Obsidian path

---

## Data Flow Diagrams

### Message Processing Flow

```
┌──────────────┐
│ Signal API   │
│ (Docker)     │
└──────┬───────┘
       │ GET /v1/receive/{number}
       ▼
┌──────────────┐
│ SignalClient │
│ poll_messages│
└──────┬───────┘
       │ List[MessageEnvelope]
       ▼
┌──────────────┐
│ Main Loop    │
│ (agent.py)   │
└──────┬───────┘
       │ For each message:
       ▼
┌──────────────┐
│ Log to       │──────────────────────────┐
│ Obsidian     │                          │
└──────┬───────┘                          │
       │                                  │
       ▼                                  ▼
┌──────────────┐                  ┌──────────────┐
│ Pydantic AI  │                  │ PostgreSQL   │
│ Agent.run()  │                  │ ActionLog    │
└──────┬───────┘                  └──────────────┘
       │
       │ Tool calls (0-N)
       ▼
┌──────────────────────────────────────────┐
│                  Tools                    │
│  ┌────────────┐  ┌────────────┐          │
│  │search_notes│  │ read_note  │  ...     │
│  └────────────┘  └────────────┘          │
└──────────────────────────────────────────┘
       │
       │ Response text
       ▼
┌──────────────┐
│ Log response │
│ to Obsidian  │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ SignalClient │
│ send_message │
└──────┬───────┘
       │ POST /v2/send
       ▼
┌──────────────┐
│ Signal API   │
└──────────────┘
```

### Tool Execution Flow

```
┌─────────────┐
│ Agent       │
│ decides to  │
│ call tool   │
└──────┬──────┘
       │
       ▼
┌─────────────┐     ┌─────────────┐
│ Tool func   │────▶│ Log action  │
│ executes    │     │ to Postgres │
└──────┬──────┘     └─────────────┘
       │
       │ (e.g., search_notes)
       ▼
┌─────────────┐
│ Obsidian    │
│ HTTP Client │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ Obsidian    │
│ REST API    │
└──────┬──────┘
       │
       │ Results
       ▼
┌─────────────┐
│ Format      │
│ response    │
└──────┬──────┘
       │
       │ Return to agent
       ▼
┌─────────────┐
│ Agent       │
│ continues   │
└─────────────┘
```

---

## Testing Strategy

### 1. CLI Test Mode

Add `--test` flag to `agent.py`:

```bash
poetry run python src/agent.py --test "Search for notes about Python"
```

This mode:
- Skips Signal polling
- Takes message from CLI argument
- Prints response to stdout
- Exits after single response

### 2. Unit Tests

**File: `tests/test_tools.py`**
- Test Obsidian client methods with mocked HTTP
- Test tool functions with mocked client

**File: `tests/test_agent.py`**
- Test agent creation
- Test message processing with mock tools

**File: `tests/test_signal.py`**
- Test message parsing
- Test send message formatting

### 3. Integration Tests

**File: `tests/test_integration.py`**
- Test full flow with real Obsidian (requires running instance)
- Test conversation logging
- Test multi-turn conversations

### 4. Manual Testing Checklist

Before considering Phase 1 complete:

- [ ] `--test "Hello"` returns coherent response
- [ ] `--test "Search for X"` calls search_notes tool
- [ ] `--test "Create a note about Y"` creates note in Obsidian
- [ ] Signal message received and logged to Obsidian
- [ ] Signal response sent successfully
- [ ] Conversation persisted across agent restart
- [ ] Action logs appear in PostgreSQL

---

## Configuration Requirements

### Environment Variables Needed

```bash
# Required for Phase 1
ANTHROPIC_API_KEY=sk-ant-...         # Claude API access
OBSIDIAN_API_KEY=...                  # Local REST API key
OBSIDIAN_VAULT_PATH=/path/to/vault    # Local vault path
POSTGRES_PASSWORD=...                 # Database password
SIGNAL_PHONE_NUMBER=+15551234567      # Agent's phone number (NEW)

# Optional (have defaults)
LITELLM_MODEL=claude-sonnet-4-20250514
QDRANT_URL=http://qdrant:6333
```

### New Config Fields

Add to `src/config.py`:

```python
signal.phone_number: str  # Required - agent's registered number
conversation_folder: str = "Brain/Conversations"  # Obsidian path
allowed_senders: list[str] = []  # Legacy Signal allowlist; required if no per-channel allowlist
signal.allowed_senders_by_channel: dict[str, list[str]] = {}  # Preferred per-channel allowlists; required if legacy allowlist empty
```

### Obsidian Vault Setup

Ensure these folders exist:
- `Brain/` - Root folder for agent content
- `Brain/Conversations/` - Conversation logs
- `Brain/Conversations/2026/` - Year folder
- `Brain/Conversations/2026/01/` - Month folder (created automatically)

---

## Rollout Plan

### Step 1: Implement Core Agent (No Signal)

1. Update `src/tools/obsidian.py` with tool functions
2. Create `src/tools/memory.py`
3. Create `src/services/database.py`
4. Rewrite `src/agent.py` with Pydantic AI
5. Test with `--test` flag

**Validation:** Can process messages and call tools via CLI

### Step 2: Add Signal Integration

1. Create `src/services/signal.py`
2. Add Signal polling to main loop
3. Add response sending
4. Update config with phone number

**Validation:** Can receive and respond to Signal messages

### Step 3: Add Conversation Persistence

1. Implement conversation note creation
2. Add message logging
3. Test conversation continuity

**Validation:** Conversations appear in Obsidian, persist across restarts

### Step 4: Polish and Test

1. Add comprehensive error handling
2. Write unit tests
3. Manual testing checklist
4. Update README with usage instructions

**Validation:** All checklist items pass

---

## Continuation Notes

### If Implementation Is Interrupted

This section provides context for a new agent/context continuing the work.

#### Key Files and Their Roles

| File | Role | Priority |
|------|------|----------|
| `src/agent.py` | Main entry point, agent definition | Critical |
| `src/tools/obsidian.py` | Obsidian tools for agent | Critical |
| `src/services/signal.py` | Signal message I/O | High |
| `src/tools/memory.py` | Conversation persistence | High |
| `src/services/database.py` | PostgreSQL session management | Medium |

#### Pydantic AI Patterns to Follow

**Tool Registration:**
```python
from pydantic_ai import Agent, RunContext

agent = Agent(
    'anthropic:claude-sonnet-4-20250514',
    deps_type=AgentDeps,
    system_prompt="..."
)

@agent.tool
async def search_notes(ctx: RunContext[AgentDeps], query: str) -> str:
    """Search Obsidian vault for notes matching query."""
    client = ctx.deps.obsidian
    results = await client.search(query)
    # Format and return
```

**Running the Agent:**
```python
result = await agent.run(
    user_message,
    deps=AgentDeps(user=settings.user.name, obsidian=ObsidianClient(), ...)
)
response_text = result.data
```

#### Common Pitfalls

1. **Import paths**: Files run from `/app/` in Docker, use relative imports carefully
2. **Async context**: All tool functions must be async
3. **Obsidian API**: Content-Type for note creation is `text/markdown`, not JSON
4. **Signal API**: Phone numbers must include country code (+1...)
5. **Pydantic AI version**: Using `>=0.0.14`, API may differ from older tutorials

#### Testing Without Full Stack

To test without Docker:
1. Run Obsidian with Local REST API plugin locally
2. Use `--test` mode to skip Signal

#### What "Done" Looks Like

Phase 1 is complete when:
1. `poetry run python src/agent.py --test "Hello"` works
2. `poetry run python src/agent.py` polls Signal and responds
3. Conversations appear in `Brain/Conversations/` in Obsidian
4. Actions appear in `action_logs` table in PostgreSQL
5. Agent survives restarts without losing conversation context

---

## Appendix A: Signal API Reference

### Receive Messages

```
GET /v1/receive/{number}
```

Response:
```json
[
  {
    "envelope": {
      "source": "+15551234567",
      "sourceDevice": 1,
      "timestamp": 1704067200000,
      "dataMessage": {
        "timestamp": 1704067200000,
        "message": "Hello Brain",
        "expiresInSeconds": 0
      }
    }
  }
]
```

### Send Message

```
POST /v2/send
Content-Type: application/json

{
  "message": "Hello!",
  "number": "+15559876543",
  "recipients": ["+15551234567"]
}
```

---

## Appendix B: Obsidian REST API Reference

### Search

```
POST /search/simple/
Authorization: Bearer {api_key}
Content-Type: application/json

{"query": "search term"}
```

### Create Note

```
POST /vault/{path}
Authorization: Bearer {api_key}
Content-Type: text/markdown

Note content here...
```

### Append to Note

```
PATCH /vault/{path}
Authorization: Bearer {api_key}
Content-Type: text/markdown

Content to append...
```

---

## Appendix C: Pydantic AI Quick Reference

### Agent Creation

```python
from pydantic_ai import Agent

agent = Agent(
    'anthropic:claude-sonnet-4-20250514',  # Model identifier
    deps_type=MyDeps,                       # Dependency type
    system_prompt="You are..."              # System prompt
)
```

### Tool Definition

```python
@agent.tool
async def my_tool(ctx: RunContext[MyDeps], param: str) -> str:
    """Docstring is shown to the LLM to help it decide when to use this tool."""
    # Access dependencies via ctx.deps
    return "result"
```

### Running

```python
result = await agent.run("User message", deps=my_deps)
print(result.data)  # Response text
print(result.all_messages())  # Full conversation
```

### Test Mode

```python
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

agent = Agent(TestModel())  # Mock model for testing
```
