# Project Layout
This document maps the repository's directory structure to the conceptual model
described in [Boundaries & Responsibilities](boundaries-and-responsibilities.md).

> Check the [Glossary](glossary.md) for key terms such as _Layer_, _System_, _Resource_,
> _Service_, et cetera.

------------------------------------------------------------------------
## Top-Level Directories
| Directory | Purpose |
|---|---|
| `actors/` | L2 _Actor_ processes: `agent/`, `beat/`, `cli/`, `worker/` |
| `config/` | Configuration samples (`brain.yaml.sample`) |
| `docs/` | Architecture & contributor documentation |
| `generated/` | Auto-generated Python from Protobuf (git-ignored) |
| `host-mcp-gateway/` | Go-based HTTP proxy for host-level MCP Servers |
| `img/` | Diagrams and images referenced by docs and README |
| `packages/` | Shared Python packages (see below) |
| `prompts/` | LLM prompt templates (`embedding/`, `inference/`, `config/`) |
| `protos/` | Protobuf definitions (`protos/brain/`) |
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
    policy_engine/
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
| `api.py` | gRPC _Service_ adapter (bridges SDK to _Public API_) |
| `data/` | Data layer: `schema.py`, `repository.py`, `runtime.py` |
| `migrations/` | Alembic env: `alembic.ini`, `env.py`, `versions/` |
| `tests/` | _Component_-level tests |

------------------------------------------------------------------------
## Resources
_Resources_ follow the convention `resources/<kind>/<resource>/`:

```
resources/
  adapters/                     # Adapter Resources (external I/O)
  substrates/                   # Substrate Resources (state)
    postgres/                   # Shared Infrastructure (bootstrap, engine, sessions)
    qdrant/                     # Vector search backend
```

Each _Resource_ exports a `MANIFEST` via `component.py` with a
`ResourceManifest`.

------------------------------------------------------------------------
## Packages
Shared code lives in `packages/`:

| Package | Purpose |
|---|---|
| `brain_shared/` | Cross-cutting utilities: `manifest.py` (_Component_ registry), `envelope/`, `errors/`, `ids/` (ULID helpers), `logging/`, `config/`, `embeddings.py`, `component_loader.py`; contract conventions for these shared types are defined in [Conventions](conventions.md) |
| `brain_core/` | Brain Core runtime (L1 _Service_ orchestration) |
| `brain_sdk/` | _Brain Core SDK_ for L2 _Actors_ (gRPC client) |
| `capability_sdk/` | _Capability SDK_ for _Op_/_Skill_ registration and management |

------------------------------------------------------------------------
## Protos and Generated Code
Protobuf definitions live in `protos/brain/`. Running `make build` compiles
them into Python modules in `generated/` (git-ignored). The generated code
provides the gRPC layer that backs the _Brain Core SDK_.

------------------------------------------------------------------------
## Configuration
Runtime configuration is loaded from `~/.config/brain/brain.yaml`. A sample is
provided at `config/brain.yaml.sample`. See [Configuration Reference](configuration.md)
for keys and [Conventions](conventions.md) for Pydantic contract rules.

------------------------------------------------------------------------
## Tests
- `tests/` contains shared test infrastructure and cross-cutting tests.
- _Component_-level tests live alongside their _Service_ in
  `services/<system>/<service>/tests/`.
- _Resource_-level tests live alongside their _Resource_.
- Run all tests with `make test` (see [Development Guide](development-guide.md)).

------------------------------------------------------------------------
_End of Project Layout_
