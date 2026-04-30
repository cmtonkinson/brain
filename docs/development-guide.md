# Development Guide
This document covers how to set up, build, test, and contribute to Brain.

> Check the [Glossary](glossary.md) for key terms such as *Tier*, *Plane*, *Resource*,
> *Service*, et cetera.

------------------------------------------------------------------------
## Prerequisites
* **Python 3.14**
* **Docker** and **Docker Compose** (for Postgres, Qdrant, and other services)
* **Ollama** (recommended for embedding, optional for inference)
* **Obsidian** with the Local REST API plugin

------------------------------------------------------------------------
## Environment Setup
1. Clone the repository and install Python dependencies:
   ```sh
   make deps
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
   cp config/shared.yaml.sample ~/.config/brain/shared.yaml
   cp config/state.yaml.sample ~/.config/brain/state.yaml
   cp config/effect.yaml.sample ~/.config/brain/effect.yaml
   cp config/reason.yaml.sample ~/.config/brain/reason.yaml
   cp config/actors.yaml.sample ~/.config/brain/actors.yaml
   cp config/secrets.yaml.sample ~/.config/brain/secrets.yaml
   ```
   The samples are recommended groupings only. Brain scans the config directory
   non-recursively and deep-merges top-level `*.yaml` files in lexical order,
   so you may combine or split files however you prefer. See the
   [Configuration Reference](configuration.md) for all available keys.

5. Start Brain Core. It bootstraps schemas and runs migrations automatically
   during startup.

------------------------------------------------------------------------
## Make Targets
| Target | Description |
|---|---|
| `make all` | Full pipeline: deps, clean, unit + integration tests, docs |
| `make deps` | Install Python dependencies with `uv sync` |
| `make deps-upgrade` | Update locked dependencies (set `PACKAGE=<name>` to scope) |
| `make switch-python` | Pin a Python version (`VERSION=<x.y.z>`) for the venv |
| `make clean` | Remove generated code and Python cache files |
| `make check` | Run linting and format checks (ruff) |
| `make format` | Auto-format code (ruff) |
| `make test` | Run lint checks, then pytest across `tests/`, `resources/`, `services/`, and `actors/` |
| `make test integration` | Same as `make test`, plus integration suite |
| `make test-all` | Lint + pytest + smoke + e2e + docker smoke |
| `make smoke` | Lint + smoke pytest selection |
| `make smoke-e2e` | Run the agent end-to-end smoke harness |
| `make smoke-docker` | Run the docker turn smoke harness |
| `make docs` | Regenerate glossary, service-api, http-api, op catalog, and diagrams |
| `make outline` | Print the top-level project directory outline |
| `make up` / `make app-up` | Start application Compose services (detached) |
| `make down` / `make stack-down` | Stop the full stack (app + observability) |
| `make o11y-up` / `make o11y-down` | Start/stop the observability overlay alongside shared infra |
| `make stack-up` | Start the full stack (app + observability) |
| `make ps` | Show full-stack Compose process state |

------------------------------------------------------------------------
## Optional Observability Stack
Brain can run with a local observability overlay:
```sh
docker compose -f docker-compose.yaml -f docker-compose.observability.yaml up --build
```

The overlay enables process-level OTel export for `brain-core` and
`brain-assistant`, starts an OTel Collector, runs self-hosted Langfuse,
adds Langfuse's required ClickHouse, and
uses the base SeaweedFS service as its S3-compatible blob store. It reuses the
base Postgres and Valkey services; Langfuse data is stored in a dedicated
Postgres database and in dedicated SeaweedFS bucket/prefixes, not in Brain
service schemas or Object.

Before using the overlay, replace the `replace-me` values in `.env`, especially
Langfuse secrets, SeaweedFS S3 credentials, and `LANGFUSE_OTEL_AUTH_HEADER`.

------------------------------------------------------------------------
## Running Tests
```sh
make test             # unit
make test integration # unit & integration
```

This runs `make check` first, then executes pytest.

Tests are discovered in four locations:
* `tests/` -- shared and cross-cutting tests
* `actors/` -- *Actor*-level tests in `actors/<actor>/tests`
* `services/` -- *Service*-level tests in `services/<plane>/<service>/tests/`
* `resources/` -- *Resource*-level tests in `resources/<kind>/<resource>/tests`

------------------------------------------------------------------------
## Docker Build Notes
Docker builds rely on the container-created `/app/.venv`. Keep host virtual
environments out of the build context, and do not bind-mount over `/app` in
smoke sidecars because that masks the image's installed dependencies.

------------------------------------------------------------------------
## Adding a New Service
1. Create `services/<plane>/<service>/` with an `__init__.py`.
2. Add a `component.py` exporting a `ServiceManifest` via
   `register_component()` (see [Component Design](component-design.md)).
3. Implement the *Public API* in `service.py`.
4. For database-backed *Services*:
   * Schema name is derived from the `ComponentId`.
   * Use shared ULID PK helpers targeting `<schema>.ulid_bin`.
   * Create an Alembic environment under `migrations/`.
   * See the Shared Infrastructure section of
     [Boundaries & Responsibilities](boundaries-and-responsibilities.md).
   * Keep runtime settings and typed service contracts aligned with the
     Pydantic usage rules in [Conventions](conventions.md).
5. Start Brain Core to bootstrap your schema and run migrations.
6. Add tests in `services/<plane>/<service>/tests/`.

------------------------------------------------------------------------
## Adding a New Resource
1. Create `resources/<kind>/<resource>/` (`kind` is `substrates/` or
   `adapters/`).
2. Add a `component.py` exporting a `ResourceManifest` via
   `register_component()`.
3. Set `owner_service_id` to the T2 *Service* that owns this *Resource*.
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
migrations in *Plane*-order (*State* -> *Effect* -> *Reason*) during startup.
See the Shared Infrastructure section of
[Boundaries & Responsibilities](boundaries-and-responsibilities.md) for details.


[Ruff]: https://docs.astral.sh/ruff/


------------------------------------------------------------------------
_End of Development Guide_
