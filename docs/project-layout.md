# Project Layout
This document maps the repository's directory structure to the
conceptual model described in
[Boundaries & Responsibilities](boundaries-and-responsibilities.md).

> Check the [Glossary](glossary.md) for key terms such as *Tier*,
> *Plane*, *Resource*, *Service*, et cetera.

------------------------------------------------------------------------
## Top-Level Directories
| Directory    | Purpose                                            |
|--------------|----------------------------------------------------|
| `actors/`    | T3 *Actor* processes: `assistant/`, `cli/`,        |
|              | `console/`, `subagent/`, `worker/`                 |
| `bin/`       | Convenience launcher scripts for local development |
| `config/`    | Configuration samples and observability templates  |
| `data/`      | Docker-mounted persistent volumes                  |
| `docs/`      | Architecture & contributor documentation           |
| `img/`       | Diagrams and images referenced by docs and README  |
| `lib/`       | Shared Python packages (see below)                 |
| `logs/`      | Runtime log output                                 |
| `ops/`       | *Op* packages (see [Op Design](op-design.md))      |
| `resources/` | T1 *Resource* implementations                      |
| `scripts/`   | Build, generation, and smoke-test scripts          |
| `services/`  | T2 *Service* implementations                       |
| `tests/`     | Cross-cutting and shared test infrastructure       |

------------------------------------------------------------------------
## Services
*Services* follow the convention `services/<system>/<service>/`.
The three *Planes* map directly to subdirectories:
```
services/
  state/                        # State Plane (substrate-owners)
    cache/
    embedding/
    object/
    vault/
  effect/                       # Effect Plane (adapter-owners)
    execution/
    language/
    relay/                      # combined inbound + outbound + approval
  reason/                       # Reason Plane (no resource ownership)
    commitment/
    delegation/
    ingestion/
    job/
    policy/
    recall/
    utility/
```

Each *Service* directory contains a `component.py` with its
`ServiceManifest` registration. A fully built-out *Service*
(e.g. `embedding/`) includes:

| File/Dir            | Role                                          |
|---------------------|-----------------------------------------------|
| `component.py`      | `ServiceManifest` declaration & registration  |
| `service.py`        | *Public API* class (canonical interface)      |
| `implementation.py` | Internal business logic                       |
| `interfaces.py`     | Abstract interfaces / protocols               |
| `domain.py`         | Domain models and value objects               |
| `config.py`         | Service-scoped Pydantic settings model        |
| `boot.py`           | Service boot/runtime wiring                   |
| `validation.py`     | Input validation helpers                      |
| `api.py`            | FastAPI route registrar for SDK-facing routes |
| `data/`             | `schema.py`, `repository.py`, `runtime.py`    |
| `migrations/`       | Alembic env and version scripts               |
| `tests/`            | *Component*-level tests                       |
| `README.md`         | Service-local notes for contributors          |

------------------------------------------------------------------------
## Resources
*Resources* follow the convention `resources/<kind>/<resource>/`:
```
resources/
  adapters/                     # Adapter Resources (external I/O)
    llm/                        # LLM gateway adapter
    mcp/                        # MCP Server sidecar adapter
    signal/                     # Signal messaging adapter
  substrates/                   # Substrate Resources (state)
    obsidian/                   # Obsidian vault (Local REST API)
    postgres/                   # Shared RDBMS infrastructure
    qdrant/                     # Vector search backend
    seaweedfs/                  # S3-compatible blob storage
    valkey/                     # Cache and queue backend
```

Each *Resource* exports a `MANIFEST` via `component.py` with a
`ResourceManifest`.

------------------------------------------------------------------------
## Packages
Shared code lives in `lib/`:

| Package      | Purpose                                         |
|--------------|-------------------------------------------------|
| `shared/`    | Cross-cutting utilities: *Component* registry,  |
|              | envelope, errors, HTTP wrappers, ULID helpers,  |
|              | logging, config, observability, embeddings.     |
|              | See [Conventions](conventions.md).              |
| `core/`      | Brain Core runtime (T2 *Service* orchestration) |
| `agent/`     | Inference loop, tool model, turn state, and     |
|              | recovery primitives shared by agent *Actors*    |
| `sdk/`       | *Brain Core SDK* for T3 *Actors* (thin HTTP     |
|              | client over the Core HTTP API)                  |
| `dashboard/` | Terminal dashboard utilities                    |

------------------------------------------------------------------------
## Configuration
Runtime configuration is loaded by scanning top-level `*.yaml` files in
`~/.config/brain/` non-recursively. Matching sample groupings are provided
under `config/` as `shared`, `state`, `effect`, `reason`, `actors`, and
`secrets` samples. See [Configuration Reference](configuration.md) for keys
and [Conventions](conventions.md) for Pydantic contract rules.

------------------------------------------------------------------------
## Tests
* `tests/` contains shared test infrastructure and cross-cutting
  tests.
* *Component*-level tests live alongside their *Service* in
  `services/<system>/<service>/tests/`.
* *Resource*-level tests live alongside their *Resource*.
* Run all tests with `make test` (see [Development
  Guide](development-guide.md)).


------------------------------------------------------------------------
_End of Project Layout_
