# Brain Database
Postgres is shared infrastructure in Brain, but data ownership is strict and
Service-local. This guide is for contributors adding or modifying Components.

## Ownership Model
- Each L1 Service owns exactly one schema.
- Schema name is derived from the Service `ComponentId` (not config).
- Services may only access their own schema.
- Cross-schema joins are prohibited.
- Cross-service foreign keys are prohibited.

## Primary Key Standard
- All table PKs are ULIDs stored as 16-byte binary.
- Canonical DB type is the schema-local domain: `<schema>.ulid_bin`.
- ULIDs are generated in application code, never in Postgres.
- Shared helpers are in `packages/brain_shared/ids/` (backed by `python-ulid`).

## Migration Bootstrap
`make migrate` does this, in order:
1. Imports self-registering component modules (`*/component.py`).
2. Validates manifest registry ownership/invariants.
3. For each registered Service schema:
   - creates schema if missing
   - creates `<schema>.ulid_bin` domain if missing
4. Runs Alembic migrations in System-order (`state` → `action` → `control`)

## Contributor Checklist (New Service)
1. Add `services/<system>/<service>/component.py` with `ServiceManifest`.
2. Keep schema identity derived from `ComponentId`.
3. Use shared ULID PK helpers that target `<schema>.ulid_bin`.
4. Keep migrations in that Service's own Alembic environment only.
5. Never query/mutate other Service schemas directly.
