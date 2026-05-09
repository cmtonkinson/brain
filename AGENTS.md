Do ~/.config/agents/agents.md now.

Additional instructions for working in this specific project:
* @README.md
* @docs/*.md
* `python -m pytest ...` for targeted verification
* `ruff [format]` for linting / style enforcement
* `gmake test` for comprehensive basic checks - docs, lint, unit (takes ~12)
* `gmake test integration` for unit+integration tests (~40s)
* `gmake test-all` for full suite, incl. e2e smoke tests (~2m)
* Forward state changes that touch user data on the host or in stateful
  substrates go through the Upgrades system (see `docs/upgrades.md` and
  `upgrades/`). Per-service SQL schema changes go through Alembic.
* In-process Python contracts have no backwards-compat expectation.
  Identifier renames propagate through the codebase; dead code is pruned, not
  preserved.
* Don't leave notes about what things "used to" be called.
* Configuration parameters > module-level constants > magic scalars
* Configuration parameters should:
  * have a sane default
  * be shown in the appropriate `.yaml.sample` file
  * be shown in `docs/configuration.md`
* Do not hardcode prompts or prompt templates; all context assembly and
  manipulation must be done through InferenceRequest and its related objects.
  Only the LLM Adapter may flatten and serialize data for LLM API calls.
* Python 3.14 (PEP 758) allows `except A, B:` without parentheses; this is
  valid syntax in this project, and ruff's formatter emits the unparenthesised
  form. Don't "fix" it.

Recent-turn analysis pointers:
* Start with service state: `docker compose ps`.
* Check recent service logs with timestamps: `docker compose logs --since 10m
  brain-core brain-assistant brain-worker brain-subagent`.
* Include adapter/substrate logs when relevant: `docker compose logs --since
  10m postgres valkey qdrant seaweedfs signal-api brain-mcp`.
* Inspect Postgres read-only via compose: `docker compose exec postgres psql -U
  brain -d brain`.
* List schemas/tables in `psql` with `\dn` and `\dt service_recall.*`; common
  turn-debug tables include `service_recall.turn`, `service_recall.session`,
  and `service_language.call_audits`.
* Useful recent-turn SQL snippets:
  * `select id, session_id, direction, role, trace_id, created_at from
    service_recall.turn order by created_at desc limit 20;`
  * `select trace_id, provider, model, operation, request_phase, outcome_kind,
    duration_ms, error_message, created_at from service_language.call_audits
    order by created_at desc limit 20;`
