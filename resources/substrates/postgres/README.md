# Postgres Substrate
Shared PostgreSQL infrastructure for Brain _Services_ that provides engine/session primitives, schema bootstrap, and normalized database error mapping.

------------------------------------------------------------------------
## What This Component Is
`resources/substrates/postgres/` is a _Substrate_ _Resource_ that centralizes:
- SQLAlchemy engine construction (`engine.py`)
- transaction/session lifecycle helpers (`session.py`)
- service-schema scoped session access (`schema_session.py`)
- migration bootstrap for per-service schemas and `ulid_bin` domains (`bootstrap.py`)
- health probing (`health.py`)
- DB error normalization into shared structured errors (`errors.py`)

Its manifest is declared in `resources/substrates/postgres/component.py` as
`substrate_postgres`.

------------------------------------------------------------------------
## Boundary and Ownership
Postgres is intentionally modeled as shared infrastructure, not a single-service
owned substrate. The manifest sets `owner_service_id=None` and exposes common
primitives that each _Service_ uses for its own schema only.

This component does not implement business rules or cross-service policy; it
provides the constrained data-access substrate that _Services_ compose with
their own repositories and domain logic.

------------------------------------------------------------------------
## Interactions
Primary interactions with the rest of the system:
- _Services_ construct engines with `create_postgres_engine(...)`.
- _Services_ open sessions via `create_session_factory(...)` and
  `transactional_session(...)`.
- _Services_ that require schema pinning use `ServiceSchemaSessionProvider`,
  which sets `SET LOCAL search_path TO <schema>, public` per transaction.
- migration/bootstrap flows call `bootstrap_service_schemas(...)` to provision
  registered service schemas and schema-local `ulid_bin`.
- service implementations map DB exceptions through
  `normalize_postgres_error(...)` before returning envelope errors.

Current usage includes the Embedding Authority _Service_ data runtime and
repository paths.

------------------------------------------------------------------------
## Operational Flow (High Level)
1. Configuration is loaded into `PostgresSettings`.
2. `create_postgres_engine(...)` builds an engine with pool/timeouts/SSL args.
3. A session factory is created from that engine.
4. Request-scope repository work runs in `transactional_session(...)` (commit on
   success, rollback on failure).
5. For service-owned schema isolation, `ServiceSchemaSessionProvider.session()`
   applies local `search_path` before queries execute.
6. During bootstrap/migrations, `bootstrap_service_schemas(...)` imports
   registered components, validates the registry, and creates missing schemas and
   `<schema>.ulid_bin` domains.

------------------------------------------------------------------------
## Failure Modes and Error Semantics
- connectivity/timeouts are surfaced as dependency-unavailable semantics.
- malformed or invalid SQL/interface failures are surfaced as dependency-failure
  semantics.
- unique-constraint collisions are surfaced as conflict/already-exists
  semantics.
- unknown failures map to internal/unexpected-exception semantics.

Mappings are implemented in `resources/substrates/postgres/errors.py` and return
`packages.brain_shared.errors.ErrorDetail` instances.

------------------------------------------------------------------------
## Configuration Surface
This component consumes settings from `components.substrate.postgres`:
- `url`
- `pool_size`
- `max_overflow`
- `pool_timeout_seconds`
- `pool_pre_ping`
- `connect_timeout_seconds`
- `sslmode`
- `host`
- `port`
- `database`
- `user`
- `password`

See `docs/configuration.md` for full key definitions and environment override
rules.

------------------------------------------------------------------------
## Testing and Validation
Component tests covering this substrate include:
- `resources/substrates/postgres/tests/test_postgres_config.py`
- `resources/substrates/postgres/tests/test_error_normalization.py`

Project-wide validation command:
```bash
make test
```

------------------------------------------------------------------------
## Contributor Notes
- Keep this component focused on infrastructure concerns only.
- Do not add business-domain rules here; keep those in owning _Services_.
- Maintain strict schema isolation: service code must use only its own schema.
- Keep error normalization stable and explicit so envelope error behavior is
  predictable for callers.
- If the exported substrate API changes, update this README and any affected
  references in `docs/`.

------------------------------------------------------------------------
_End of Postgres Substrate README_
