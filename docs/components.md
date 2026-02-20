# Component Design

## 1) Component Rules (Global)
A **Component** is any registered unit of functionality in Brain and must be one
of:
- **Resource** (L0)
- **Service** (L1)
- **Actor** (L2)

All Components are defined by and must self-register through
`packages/brain_shared/manifest.py`.

### Required semantics
- Every Component has a globally unique `ComponentId`.
- Every Component declares `layer`, `system`, and one or more `module_roots`.
- `ComponentId` is schema-safe (`^[a-z][a-z0-9_]{1,62}$`).
- Registration is global and process-local via `register_component(...)`.
- Registry is the source of truth for identity and ownership validation.

### Registry behavior
- One global registry contains all component types.
- `list_components()` is the canonical complete view.
- Ownership checks are enforced for L0/L1 relationships:
  - on registration (non-strict owner existence; import-order tolerant)
  - on `assert_valid()` (strict owner existence)

## 2) L0 Resource Design
An L0 Resource is infrastructure with durable or real-world side effects.

### Model
- Declared via `ResourceManifest`.
- Required:
  - `id: ComponentId`
  - `layer = 0`
  - `kind in {"substrate", "adapter"}`
  - `module_roots`
- Optional:
  - `owner_service_id` (required in practice for owned resources)

### Architectural expectations
- L0 access is gated by owning L1 Service(s), never by L2 directly.
- Resource ownership must be explicit and unambiguous.
- If `owner_service_id` is set, it must resolve to a registered L1 Service.
- Resource IDs must match what owning services declare in `owns_resources`.

### Implementation expectations
- Package should export a top-level `MANIFEST` constant that calls
  `register_component(ResourceManifest(...))`.
- Resource modules contain substrate/adapter implementation, not business
  policy.

## 3) L1 Service Design
An L1 Service is Brain business logic with authoritative public contracts.

### Model
Declared via `ServiceManifest`. Required:
  - `id: ComponentId`
  - `layer = 1`
  - `system in {"state", "action", "control"}`
  - `module_roots`
  - `public_api_roots`
  - `owns_resources: FrozenSet[ComponentId]`

### Architectural expectations
- Services may call other services **only** through their public APIs.
- Services may not import other services' internal implementations.
- Services gate all L0 access and enforce domain invariants/policy.
- Service ID is canonical for schema naming (`schema_name == ComponentId`).
- For PostgreSQL, which is a shared Substrate:
  - each Service owns exactly its schema
  - no cross-schema direct access
  - no cross-service foreign keys
  - this means you have to do joins and RI in code; deal with it

### Implementation expectations
- Service package should export `MANIFEST =
  register_component(ServiceManifest(...))`.
- `owns_resources` must list L0 component IDs it owns.
- If a Resource declares `owner_service_id`, it must match the owning Service
  `id`.
- Public API methods exposed must be decorated with
  `packages.brain_shared.logging.public_api_instrumented(...)` so invocation
  observability concerns (logging, metrics, tracing) remain consistent and
  composable across Services.

## 4) Practical Registration Pattern
Each component package should self-register at import time with a single exported `MANIFEST` symbol:
- Service example: `services/state/<service>/__init__.py`
- Resource example: `resources/substrates/<resource>/__init__.py`

This enables deterministic pre-flight checks and bootstrap orchestration from the global registry.
