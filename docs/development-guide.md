# Development Guide
This document covers how to set up, build, test, and contribute to Brain.

> Check the [Glossary](glossary.md) for key terms such as _Layer_, _System_, _Resource_,
> _Service_, et cetera.

------------------------------------------------------------------------
## Prerequisites
- **Python 3.13**
- **Docker** and **Docker Compose** (for Postgres, Qdrant, and other services)
- **Ollama** (recommended for embedding, optional for inference)
- **Obsidian** with the Local REST API plugin

------------------------------------------------------------------------
## Environment Setup
1. Clone the repository and install Python dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Start infrastructure services:
   ```
   cp .env.sample .env
   make up
   ```
   This runs Docker Compose, which starts Postgres, Qdrant, `signal-api`, and
   any other containerized services defined in `docker-compose.yaml`.

3. If migrating existing signal-cli account state, copy it into `./data/signal-cli`:
   ```
   mkdir -p ./data/signal-cli
   cp -R /path/to/existing/signal-cli/. ./data/signal-cli/
   ```
   Copy, do not move, until webhook ingress and account state are verified in
   this deployment.

4. Copy and edit the configuration sample:
   ```
   cp config/brain.yaml.sample ~/.config/brain/brain.yaml
   ```
   The sample includes defaults for `components.substrate_postgres.url`,
   `components.adapter_signal.base_url`, and Signal profile settings; override
   them as needed for your environment. See the
   [Configuration Reference](configuration.md) for all available keys.

5. Run database migrations:
   ```
   make migrate
   ```

`deprecated/` is not part of this runtime path and remains reference-only.

------------------------------------------------------------------------
## Make Targets
| Target | Description |
|---|---|
| `make all` | Full pipeline: deps, clean, build, test, docs |
| `make deps` | Install Python dependencies from `requirements.txt` |
| `make clean` | Remove generated code and Python cache files |
| `make build` | Compile Protobufs into `generated/` |
| `make check` | Run linting and format checks (ruff) |
| `make format` | Auto-format code (ruff) |
| `make test` | Build, lint, then run pytest across `tests/`, `services/`, and `resources/` |
| `make docs` | Regenerate glossary, service-api docs, and diagrams |
| `make migrate` | Bootstrap schemas and run Alembic migrations for all _Services_ |
| `make up` | Start Docker Compose services (detached) |
| `make down` | Stop Docker Compose services |

------------------------------------------------------------------------
## Running Tests
```
make test
```

This runs `make build` and `make check` first, then executes pytest. Tests are
discovered in three locations:
- `tests/` -- shared and cross-cutting tests
- `services/` -- _Component_-level tests in `services/<system>/<service>/tests/`
- `resources/` -- _Resource_-level tests

------------------------------------------------------------------------
## Adding a New Service
1. Create `services/<system>/<service>/` with an `__init__.py`.
2. Add a `component.py` exporting a `ServiceManifest` via
   `register_component()` (see [Component Design](component-design.md)).
3. Implement the _Public API_ in `service.py`.
4. For database-backed _Services_:
   - Schema name is derived from the `ComponentId`.
   - Use shared ULID PK helpers targeting `<schema>.ulid_bin`.
   - Create an Alembic environment under `migrations/`.
   - See the Shared Infrastructure section of
     [Boundaries & Responsibilities](boundaries-and-responsibilities.md).
   - Keep runtime settings and typed service contracts aligned with the
     Pydantic usage rules in [Conventions](conventions.md).
5. Run `make migrate` to bootstrap your schema.
6. Add tests in `services/<system>/<service>/tests/`.

------------------------------------------------------------------------
## Adding a New Resource
1. Create `resources/<kind>/<resource>/` (`kind` is `substrates/` or
   `adapters/`).
2. Add a `component.py` exporting a `ResourceManifest` via
   `register_component()`.
3. Set `owner_service_id` to the L1 _Service_ that owns this _Resource_.
4. See [Component Design](component-design.md) for full registration details.

------------------------------------------------------------------------
## Contributing Documentation
When writing or editing documentation, follow the formatting rules in
[Documentation Conventions](meta/documentation-conventions.md). For per-component
README files, follow [Component README Guide](meta/component-readme-guide.md).

------------------------------------------------------------------------
## Linting and Formatting
Brain uses [Ruff] for both linting and formatting. Configuration is in
`ruff.toml`.

```
make check    # lint + format check
make format   # auto-format
```

------------------------------------------------------------------------
## Running Migrations
```
make migrate
```

This bootstraps schemas, creates the `ulid_bin` domain, and runs Alembic
migrations in _System_-order (_State_ -> _Action_ -> _Control_). See the Shared
Infrastructure section of [Boundaries & Responsibilities](boundaries-and-responsibilities.md) for details.


[Ruff]: https://docs.astral.sh/ruff/

------------------------------------------------------------------------
_End of Development Guide_
