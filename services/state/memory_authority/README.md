# Memory Authority Service
State _Service_ that owns session-scoped Profile, Dialogue, and Focus context assembly for the Brain Agent.
------------------------------------------------------------------------
## What This Component Is
`services/state/memory_authority/` is the authoritative Layer 1 _Service_ for agent recall and context assembly behavior.

Core module roles:
- `component.py`: `ServiceManifest` registration (`service_memory_authority`)
- `service.py`: authoritative in-process public API contract
- `implementation.py`: concrete MAS behavior (`DefaultMemoryAuthorityService`)
- `domain.py`: strict payload contracts for session/context models
- `profile.py`: read-only profile context loader from MAS settings
- `dialogue.py`: turn storage and dialogue assembly with lazy summary generation
- `focus.py`: focus persistence and budget-aware compaction
- `assembler.py`: Profile/Focus/Dialogue context orchestration
- `data/`: Postgres runtime, schema, and repository implementation
- `migrations/`: Alembic environment and schema migrations
------------------------------------------------------------------------
## Boundary and Ownership
MAS is a State-System _Service_ (`layer=1`, `system="state"`) and does not declare ownership of a dedicated L0 _Resource_ component; it uses shared Postgres infrastructure for authoritative state.

Authority boundaries:
- MAS owns Profile configuration projection for context assembly.
- MAS owns Dialogue turn/session/summary records in its own Postgres schema (`service_memory_authority`).
- MAS owns Focus state and compaction policy.
- MAS does not own durable Reference memory in the vault; integration is TODO-marked in context assembly.
------------------------------------------------------------------------
## Interactions
Primary interactions:
- Callers use `MemoryAuthorityService` (`service.py`) as the canonical in-process API.
- MAS calls `LanguageModelService` public API (`chat(..., profile=ReasoningLevel.QUICK)`) for dialogue summarization and focus compaction side effects.
- MAS persists authoritative rows through `PostgresMemoryRepository` with schema-scoped sessions from `MemoryPostgresRuntime`.
- MAS maps validation, not-found, dependency, and Postgres failures into envelope errors.
------------------------------------------------------------------------
## Operational Flow (High Level)
1. `create_session` creates a new MAS session with null focus and null dialogue pointer.
2. `assemble_context` appends inbound turn, lazily summarizes older dialogue segments as needed, then assembles Profile + Focus + Dialogue into `ContextBlock`.
3. `record_response` appends outbound turn metadata after inference completes.
4. `update_focus` persists focus text and compacts via LMS when token budget is exceeded (one retry max).
5. `clear_session` advances dialogue pointer to latest turn and clears focus without deleting historical rows.
------------------------------------------------------------------------
## Failure Modes and Error Semantics
- Invalid metadata/request fields return validation-category errors.
- Missing sessions return not-found-category errors.
- Postgres errors normalize via shared `normalize_postgres_error(...)`.
- LMS failures during summary/compaction surface as dependency-category failures (compaction is explicit failure; summary generation degrades to verbatim turns).
------------------------------------------------------------------------
## Configuration Surface
MAS settings are sourced from `components.service_memory_authority`:
- `dialogue_recent_turns`
- `dialogue_older_turns`
- `focus_token_budget`
- `profile.operator_name`
- `profile.brain_name`
- `profile.brain_verbosity`
------------------------------------------------------------------------
## Testing and Validation
Component tests:
- `services/state/memory_authority/tests/test_service.py`

Project-wide validation command:
```bash
make test
```
------------------------------------------------------------------------
## Contributor Notes
- Preserve strict schema ownership (`service_memory_authority`) with no cross-schema data access.
- Keep LMS calls constrained to the LMS public API surface.
- Keep summary/compaction behavior observable and explicit; do not silently swallow durable-state failures.
------------------------------------------------------------------------
_End of Memory Authority Service README_
