# Project Layout
This document maps the repository's directory structure to the
conceptual model described in
[Boundaries & Responsibilities](boundaries-and-responsibilities.md).

> Check the [Glossary](glossary.md) for key terms such as _Tier_,
> _Plane_, _Resource_, _Service_, et cetera.

------------------------------------------------------------------------
## Top-Level Directories
| Directory    | Purpose                                            |
|--------------|----------------------------------------------------|
| `actors/`    | T3 _Actor_ processes: `agent/`, `cli/`,            |
|              | `console/`, `worker/`                              |
| `bin/`       | Convenience launcher scripts for local development |
| `config/`    | Configuration samples and observability templates  |
| `data/`      | Docker-mounted persistent volumes                  |
| `docs/`      | Architecture & contributor documentation           |
| `img/`       | Diagrams and images referenced by docs and README  |
| `lib/`       | Shared Python packages (see below)                 |
| `logs/`      | Runtime log output                                 |
| `ops/`       | _Op_ packages (see [Op Design](op-design.md))      |
| `resources/` | T1 _Resource_ implementations                      |
| `scripts/`   | Build, generation, and smoke-test scripts          |
| `services/`  | T2 _Service_ implementations                       |
| `tests/`     | Cross-cutting and shared test infrastructure       |

------------------------------------------------------------------------
## Services
_Services_ follow the convention `services/<system>/<service>/`.
The three _Planes_ map directly to subdirectories:
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
    ingestion/
    job/
    policy/
    recall/
    utility/
```

Each _Service_ directory contains a `component.py` with its
`ServiceManifest` registration. A fully built-out _Service_
(e.g. `embedding/`) includes:

| File/Dir            | Role                                          |
|---------------------|-----------------------------------------------|
| `component.py`      | `ServiceManifest` declaration & registration  |
| `service.py`        | _Public API_ class (canonical interface)      |
| `implementation.py` | Internal business logic                       |
| `interfaces.py`     | Abstract interfaces / protocols               |
| `domain.py`         | Domain models and value objects               |
| `api.py`            | FastAPI route registrar for SDK-facing routes |
| `data/`             | `schema.py`, `repository.py`, `runtime.py`    |
| `migrations/`       | Alembic env and version scripts               |
| `tests/`            | _Component_-level tests                       |

------------------------------------------------------------------------
## Resources
_Resources_ follow the convention `resources/<kind>/<resource>/`:
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

Each _Resource_ exports a `MANIFEST` via `component.py` with a
`ResourceManifest`.

------------------------------------------------------------------------
## Packages
Shared code lives in `lib/`:

| Package      | Purpose                                         |
|--------------|-------------------------------------------------|
| `shared/`    | Cross-cutting utilities: _Component_ registry,  |
|              | envelope, errors, HTTP wrappers, ULID helpers,  |
|              | logging, config, observability, embeddings.     |
|              | See [Conventions](conventions.md).              |
| `core/`      | Brain Core runtime (T2 _Service_ orchestration) |
| `sdk/`       | _Brain Core SDK_ for T3 _Actors_ (thin HTTP     |
|              | client over the Core Unix socket)               |
| `dashboard/` | Terminal dashboard utilities                    |

## Configuration
Runtime configuration is loaded by scanning top-level `*.yaml` files in
`~/.config/brain/` non-recursively. Matching sample groupings are provided
under `config/` as `shared`, `state`, `effect`, `reason`, `actors`, and
`secrets` samples. See [Configuration Reference](configuration.md) for keys
and [Conventions](conventions.md) for Pydantic contract rules.

------------------------------------------------------------------------
## Tests
- `tests/` contains shared test infrastructure and cross-cutting
  tests.
- _Component_-level tests live alongside their _Service_ in
  `services/<system>/<service>/tests/`.
- _Resource_-level tests live alongside their _Resource_.
- Run all tests with `make test` (see [Development
  Guide](development-guide.md)).


------------------------------------------------------------------------
_End of Project Layout_
