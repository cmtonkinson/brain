# Project Layout
This document maps the repository's directory structure to the conceptual model
described in [Boundaries & Responsibilities](boundaries-and-responsibilities.md).

> Check the [Glossary](glossary.md) for key terms such as _Layer_, _System_, _Resource_,
> _Service_, et cetera.

------------------------------------------------------------------------
## Top-Level Directories
| Directory | Purpose |
|---|---|
| `actors/` | L2 _Actor_ processes: `agent/`, `cli/`, `worker/` |
| `config/` | Configuration samples (`core.yaml.sample`, `resources.yaml.sample`, `actors.yaml.sample`) |
| `docs/` | Architecture & contributor documentation |
| `host-mcp-gateway/` | Go-based HTTP proxy for host-level MCP Servers |
| `img/` | Diagrams and images referenced by docs and README |
| `packages/` | Shared Python packages (see below) |
| `prompts/` | LLM prompt templates (`embedding/`, `inference/`, `config/`) |
| `resources/` | L0 _Resource_ implementations |
| `scripts/` | Build/generation scripts (glossary, service-api docs) |
| `services/` | L1 _Service_ implementations |
| `tests/` | Cross-cutting and shared test infrastructure |

------------------------------------------------------------------------
## Services
_Services_ follow the convention `services/<system>/<service>/`. The three
_Systems_ map directly to subdirectories:

```
services/
  state/                        # State System (Authorities)
    cache_authority/
    embedding_authority/
    memory_authority/
    object_authority/
    vault_authority/
  action/                       # Action System
    attention_router/
    capability_engine/
    language_model/
    policy_service/
    switchboard/
  control/                      # Control System
    commitment/
    ingestion/
    job/
```

Each _Service_ directory contains at minimum an `__init__.py` with its
`ServiceManifest` registration. A fully built-out _Service_ (e.g.
`embedding_authority/`) includes:

| File/Dir | Role |
|---|---|
| `component.py` | `ServiceManifest` declaration and registration |
| `service.py` | _Public API_ class (the canonical interface) |
| `implementation.py` | Internal business logic |
| `interfaces.py` | Abstract interfaces / protocols |
| `domain.py` | Domain models and value objects |
| `api.py` | FastAPI route registrar (publishes selected SDK-facing endpoints) |
| `data/` | Data layer: `schema.py`, `repository.py`, `runtime.py` |
| `migrations/` | Alembic env: `alembic.ini`, `env.py`, `versions/` |
| `tests/` | _Component_-level tests |

------------------------------------------------------------------------
## Resources
_Resources_ follow the convention `resources/<kind>/<resource>/`:

```
resources/
  adapters/                     # Adapter Resources (external I/O)
    llm/                    # LLM gateway adapter owned by Language Model Service
  substrates/                   # Substrate Resources (state)
    postgres/                   # Shared Infrastructure (bootstrap, engine, sessions)
    qdrant/                     # Vector search backend
    seaweedfs/                  # S3-compatible blob storage backend
```

Each _Resource_ exports a `MANIFEST` via `component.py` with a
`ResourceManifest`.

------------------------------------------------------------------------
## Packages
Shared code lives in `packages/`:

| Package | Purpose |
|---|---|
| `brain_shared/` | Cross-cutting utilities: `manifest.py` (_Component_ registry), `envelope/`, `errors/`, `http/` (internal HTTP wrappers), `ids/` (ULID helpers), `logging/`, `config/`, `embeddings.py`, `component_loader.py`; contract conventions for these shared types are defined in [Conventions](conventions.md) |
| `brain_core/` | Brain Core runtime (L1 _Service_ orchestration) |
| `brain_sdk/` | _Brain Core SDK_ for L2 _Actors_ (thin HTTP client over the Core Unix socket) |
| `capability_sdk/` | _Capability SDK_ for _Op_/_Skill_ registration and management |

## Configuration
Runtime configuration is loaded from `~/.config/brain/core.yaml`,
`~/.config/brain/resources.yaml`, and `~/.config/brain/actors.yaml`. Matching
samples are provided under `config/`. See [Configuration
Reference](configuration.md) for keys and [Conventions](conventions.md) for
Pydantic contract rules.

------------------------------------------------------------------------
## Tests
- `tests/` contains shared test infrastructure and cross-cutting tests.
- _Component_-level tests live alongside their _Service_ in
  `services/<system>/<service>/tests/`.
- _Resource_-level tests live alongside their _Resource_.
- Run all tests with `make test` (see [Development
  Guide](development-guide.md)).


------------------------------------------------------------------------
_End of Project Layout_
