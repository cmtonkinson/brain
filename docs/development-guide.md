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
   mkdir -p ~/.config/brain
   cp config/core.yaml.sample ~/.config/brain/core.yaml
   cp config/resources.yaml.sample ~/.config/brain/resources.yaml
   cp config/actors.yaml.sample ~/.config/brain/actors.yaml
   ```
   The samples include defaults for Core HTTP socket settings, resource
   endpoints, and actor connection settings; override them as needed for your
   environment. See the
   [Configuration Reference](configuration.md) for all available keys.

5. Start Brain Core. It bootstraps schemas and runs migrations automatically
   during startup.

`deprecated/` is not part of this runtime path and remains reference-only.

------------------------------------------------------------------------
## Make Targets
| Target | Description |
|---|---|
| `make all` | Full pipeline: deps, clean, unit + integration tests, docs |
| `make deps` | Install Python dependencies from `requirements.txt` |
| `make clean` | Remove generated code and Python cache files |
| `make check` | Run linting and format checks (ruff) |
| `make format` | Auto-format code (ruff) |
| `make test` | Run lint checks, then pytest across `tests/`, `resources/`, `services/`, and `actors/` |
| `make docs` | Regenerate glossary, service-api docs, and diagrams |
| `make outline` | Print the top-level project directory outline |
| `make up` | Start Docker Compose services (detached) |
| `make down` | Stop Docker Compose services |

------------------------------------------------------------------------
## Running Tests
```sh
make test             # unit
make test integration # unit & integration
```

This runs `make check` first, then executes pytest.

Tests are discovered in four locations:
- `tests/` -- shared and cross-cutting tests
- `actors/` -- _Actor_-level tests in `actors/<actor>/tests`
- `services/` -- _Service_-level tests in `services/<system>/<service>/tests/`
- `resources/` -- _Resource_-level tests in `resources/<kind>/<resource>/tests`

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
5. Start Brain Core to bootstrap your schema and run migrations.
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
## Database Bootstrapping
Brain Core bootstraps schemas, creates the `ulid_bin` domain, and runs Alembic
migrations in _System_-order (_State_ -> _Action_ -> _Control_) during startup.
See the Shared Infrastructure section of
[Boundaries & Responsibilities](boundaries-and-responsibilities.md) for details.


[Ruff]: https://docs.astral.sh/ruff/


------------------------------------------------------------------------
_End of Development Guide_
