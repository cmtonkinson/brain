# Recall Service
State *Service* that owns session-scoped Dialogue and Focus context assembly for the Brain Assistant.
------------------------------------------------------------------------
## What This Component Is
`services/reason/recall/` is the authoritative Tier 2 *Service* for agent recall and context assembly behavior.

Core module roles:
* `component.py`: `ServiceManifest` registration (`service_recall`)
* `service.py`: authoritative in-process public API contract
* `implementation.py`: concrete Recall behavior (`DefaultRecallService`)
* `domain.py`: strict payload contracts for session/context models
* `dialogue.py`: turn storage and dialogue assembly with rolling-summary compaction
* `focus.py`: focus persistence and budget-aware compaction
* `assembler.py`: Focus/Dialogue context orchestration
* `data/`: Postgres runtime, schema, and repository implementation
* `migrations/`: Alembic environment and schema migrations
------------------------------------------------------------------------
## Boundary and Ownership
Recall is a State-System *Service* (`tier=2`, `plane="state"`) and does not declare ownership of a dedicated T1 *Resource* component; it uses shared Postgres infrastructure for authoritative state.

Ownership boundaries:
* Recall owns Dialogue turn/session rows plus rolling summary state in its own Postgres schema (`service_recall`).
* Recall owns Focus state and compaction policy.
* Recall does not own durable Reference memory in the vault; integration is TODO-marked in context assembly.
* Recall does not own system prompt or provider/tool semantics; it returns only the
  memory-owned `memory_context` slice used by the Agent to assemble the full
  inference request.
------------------------------------------------------------------------
## Interactions
Primary interactions:
* Callers use `RecallService` (`service.py`) as the canonical in-process API.
* Recall calls `LanguageService` public API (`chat(..., profile=ReasoningLevel.QUICK)`) for dialogue summarization and focus compaction side effects.
* Recall persists authoritative rows through `PostgresMemoryRepository` with schema-scoped sessions from `MemoryPostgresRuntime`.
* Recall maps validation, not-found, dependency, and Postgres failures into envelope errors.
------------------------------------------------------------------------
## Operational Flow (High Level)
1. `create_session` creates a new Recall session with null focus and null dialogue pointer.
2. `assemble_context` appends inbound turn, rolls older unsummarized dialogue into the session summary when the verbatim backlog crosses threshold, then assembles Focus + rolling summary + recent verbatim Dialogue into the Recall-owned context block returned to the Agent.
3. `record_response` appends outbound turn metadata after inference completes.
4. `update_focus` persists focus text and compacts via Language when token budget is exceeded (one retry max).
5. `clear_session` advances dialogue pointer to latest turn and clears focus without deleting historical rows.
------------------------------------------------------------------------
## Failure Modes and Error Semantics
* Invalid metadata/request fields return validation-category errors.
* Missing sessions return not-found-category errors.
* Postgres errors normalize via shared `normalize_postgres_error(...)`.
* Language failures during summary/compaction surface as dependency-category failures (focus compaction is explicit failure; dialogue summary generation degrades to leaving more turns verbatim).
------------------------------------------------------------------------
## Configuration Surface
Recall settings are sourced from `components.service.recall`:
* `min_turns_to_keep`
* `max_turns_to_keep`
* `focus_token_budget`
------------------------------------------------------------------------
## Testing and Validation
Component tests:
* `services/reason/recall/tests/test_service.py`

Project-wide validation command:
```bash
make test
```
------------------------------------------------------------------------
## Contributor Notes
* Preserve strict schema ownership (`service_recall`) with no cross-schema data access.
* Keep Language calls constrained to the Language public API surface.
* Keep summary/compaction behavior observable and explicit; do not silently swallow durable-state failures.


------------------------------------------------------------------------
_End of Recall Service README_
