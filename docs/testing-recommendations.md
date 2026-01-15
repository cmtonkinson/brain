# Automated Testing Recommendations

Goal: reduce manual regression work while keeping tests fast and reliable. The
implementation is authoritative; use docs only for orientation.

## Recommended Test Stack
Python:
- `pytest` as the core runner
- `pytest-asyncio` for async tests
- `respx` for `httpx` request mocking
- (Optional) `pytest-cov` for coverage in CI

Go:
- `go test ./...` for package-level tests

## Test Script Layout
All scripts live under `test/`, with a root `test.sh` that runs them all:
- `test/unit.sh` -> `test/unit`
- `test/contract.sh` -> `test/contract`
- `test/integration.sh` -> `test/integration` (gated by `BRAIN_RUN_INTEGRATION=1`)
- `test/smoke.sh` -> `test/smoke`
- `test/go.sh` -> `host-mcp-gateway` Go tests

## High-ROI Unit Tests (no services)
- Indexer parsing and chunking: `src/indexer.py` functions
  - `split_sections`, `markdown_blocks`, `chunk_markdown`, `make_point_id`, `file_hash`
- Signal Markdown rendering: `_render_signal_message` in `src/agent.py`
  - Golden/snapshot tests for headings, lists, links, code blocks
- Access control: `is_sender_allowed` in `src/access_control.py`
- Conversation path and summaries: `src/tools/memory.py`
  - `get_conversation_path`, `get_summary_path`, marker formatting
- Prompt rendering: `render_prompt` in `src/prompts.py`
  - Missing placeholder errors and happy path substitutions
- Code-Mode safety detection: `_detect_destructive_ops` in `src/services/code_mode.py`

## HTTP Client Contract Tests (mocked httpx)
Use `respx` or `pytest-httpx` to validate request/response handling without
live services.
- Obsidian Local REST API: `src/tools/obsidian.py`
  - search/get/create/append paths and error handling
- Signal API: `src/services/signal.py`
  - polling parsing, send payload shape, and error cases
- Letta API: `src/services/letta.py`
  - fallback endpoints and response extraction
- Embeddings: `src/services/vector_search.py`, `src/indexer.py`
  - missing `embedding` field and error propagation

## Database Integration Tests (lightweight)
Prefer a Postgres container in CI or a local fixture.
- Migrations apply and action logging: `src/services/database.py`
- Model interactions: `src/models.py`
- Settings validation for allowlists: `src/config.py`

## Indexer Functional Tests (temp vault + stubs)
Create a temporary vault with edge-case markdown and stub embeddings/Qdrant:
- Chunk count and payload shape
- No-change detection prevents reindex
- Full reindex deletes collection
Files: `src/indexer.py`, `src/services/vector_search.py`

Optional: a single happy-path test against a real Qdrant container to catch
integration regressions.

## Agent Flow Smoke Tests (no LLM calls)
Run `process_message` with stubbed dependencies to validate:
- Obsidian write flows
- conversation logging
- formatting path for Signal
File: `src/agent.py` with stubbed `Agent` and clients.

## Go Gateway Tests (if maintaining host-mcp-gateway)
Use Go `testing` + `httptest` to cover:
- Config parsing/validation
- Auth allowlist behavior
- Request/response routing with a fake managed server
File: `host-mcp-gateway/main.go`

## Static Verification
Low-cost checks that catch regressions early:
- `ruff` and `mypy` for Python
- `go test` for Go packages

## Suggested Phase 1 Scope
Start with the highest return and least setup:
1) Indexer chunking/parsing unit tests
2) Signal Markdown rendering snapshot tests
3) Obsidian client contract tests (mocked httpx)

From there, add database integration tests and a single Qdrant happy-path test.
