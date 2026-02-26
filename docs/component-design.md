# Component Design
A _Component_ is any registered unit of functionality in Brain and must be one
of: _Resource_ (L0), _Service_ (L1), or _Actor_ (L2). All _Components_ must
self-register by calling `register_component()` from
`packages/brain_shared/manifest.py`.

> Check the [Glossary](glossary.md) for key terms such as _Component_, _Manifest_,
> _Resource_, _Service_, et cetera.

------------------------------------------------------------------------
## Component Rules (Global)
### Required semantics
- Every _Component_ has a globally unique `ComponentId`.
- Every _Component_ declares `layer`, `system`, and one or more `module_roots`.
- `ComponentId` is schema-safe (`^[a-z][a-z0-9_]{1,62}$`).
- Registration is global and process-local via `register_component(...)`.
- Registry is the source of truth for identity and ownership validation.

### Registry behavior
- One global registry contains all _Component_ types.
- `list_components()` is the canonical complete view.
- Ownership checks are enforced for L0/L1 relationships:
  - on registration (non-strict owner existence; import-order tolerant)
  - on `assert_valid()` (strict owner existence)

------------------------------------------------------------------------
## L0 Resource Design
An L0 _Resource_ is infrastructure with durable or real-world side effects.

### Model
- Declared via `ResourceManifest`.
- Required:
  - `id: ComponentId`
  - `layer = 0`
  - `kind in {"substrate", "adapter"}`
  - `module_roots`
- Optional:
  - `owner_service_id` (required in practice for owned _Resources_)

### Architectural expectations
- L0 access is gated by owning L1 _Service(s)_, never by L2 directly.
- _Resource_ ownership must be explicit and unambiguous.
- If `owner_service_id` is set, it must resolve to a registered L1 _Service_.
- _Resource_ IDs must match what owning _Services_ declare in `owns_resources`.

### Implementation expectations
- Package should export a top-level `MANIFEST` constant that calls
  `register_component(ResourceManifest(...))`.
- _Resource_ modules contain _Substrate_/_Adapter_ implementation, not business
  policy.

------------------------------------------------------------------------
## L1 Service Design
An L1 _Service_ is Brain business logic with authoritative public contracts.

### Model
Declared via `ServiceManifest`. Required:
  - `id: ComponentId`
  - `layer = 1`
  - `system in {"state", "action", "control"}`
  - `module_roots`
  - `public_api_roots`
  - `owns_resources: FrozenSet[ComponentId]`

### Architectural expectations
- _Services_ may call other _Services_ **only** through their _Public APIs_.
- _Services_ may not import other _Services'_ internal implementations.
- _Services_ gate all L0 access and enforce domain invariants/policy.
- _Service_ ID is canonical for schema naming (`schema_name == ComponentId`).
- For PostgreSQL, which is a shared _Substrate_:
  - each _Service_ owns exactly its schema
  - no cross-schema direct access
  - no cross-_Service_ foreign keys
  - this means you have to do joins and RI in code; deal with it

### Implementation expectations
- _Service_ package should export `MANIFEST =
  register_component(ServiceManifest(...))`.
- `owns_resources` must list L0 _Component_ IDs it owns.
- If a _Resource_ declares `owner_service_id`, it must match the owning
  _Service_ `id`.
- _Public API_ methods exposed must be decorated with
  `packages.brain_shared.logging.public_api_instrumented(...)` so invocation
  observability concerns (logging, metrics, tracing) remain consistent and
  composable across _Services_.
- Typed contracts (settings, envelopes, request/response models, structured
  errors) should follow the Pydantic contract rules in
  [Conventions](conventions.md).
- Service settings key definitions and override behavior should align with
  [Configuration Reference](configuration.md).

------------------------------------------------------------------------
## Optional Boot Hook Contract
Any _Component_ may define an optional `boot.py` module for startup
orchestration. This is for cross-_Component_ runtime coordination, not for
primary configuration loading.

### Ordering
- Core startup resolves configuration first.
- Boot hook orchestration runs after configuration is available.
- If any configured _Component_ hook fails under configured retry/timeout
  policy, Core startup fails hard and exits with error.

### Required symbols (when `boot.py` exists)
- `dependencies: tuple[str, ...]`
- `is_ready(ctx: BootContext) -> bool`
- `boot(ctx: BootContext) -> None`

### Semantics
- `dependencies` contains `ComponentId` values for required upstream
  _Components_.
- `is_ready(...)` must be non-blocking and return readiness truthfully.
- `boot(...)` performs one-time startup work and must raise on failure.
- Hooks receive runtime dependencies/settings via `BootContext`; _Components_
  should not rely on mutable module globals for boot state.

## Optional After-Boot Hook Contract
Any _Component_ may define an optional `after_boot(...)` function in its
`component.py` module for post-boot initialization that must run after all boot
hooks succeed.

### Ordering
- `after_boot(...)` runs after global boot orchestration completes.
- `after_boot(...)` runs before gRPC runtime starts serving.
- If any `after_boot(...)` hook raises, Core startup fails hard and exits with
  error.

### Contract
- Signature: `after_boot(*, settings: BrainSettings, components: Mapping[str, object]) -> None`
- `settings` is fully resolved typed runtime configuration.
- `components` is the instantiated component map keyed by `ComponentId`.

### Semantics
- Use this hook for post-boot initialization that requires a fully booted
  runtime graph.
- This hook is not a readiness gate and does not participate in boot
  retry/timeout policy.
- Hooks must be deterministic and raise on failure.

------------------------------------------------------------------------
## Capability Package Design
Capability packages are immutable runtime contracts owned by Capability Engine.

### Package shape
- Root location is `capabilities/`.
- Each package directory is self-named in kebab-case and must exactly match
  `capability_id`.
- Required files in every package:
  - `capability.json`
  - `README.md`
- `Op` package:
  - manifest-only wrapper over primitive call target
  - no required Python module
- Logic `Skill` package:
  - `execute.py` entrypoint module
  - `test/` with at least one `test_*.py` file
- Pipeline `Skill` package:
  - declarative `pipeline` list of capability IDs
  - no required Python module

### Manifest invariants
- Manifest schema is immutable at runtime.
- `capability_id` identifies the package and is the runtime invoke target.
- Manifest `version` is semver and is audit metadata, not a runtime selector.
- Exactly one runtime manifest version is active per `capability_id`.
- Registry validation is fail-closed at boot:
  - invalid schema fails boot
  - duplicate `capability_id` fails boot
  - unknown dependency or pipeline member fails boot
- Runtime overlays may not mutate capability manifests.

------------------------------------------------------------------------
## Practical Registration Pattern
Each _Component_ package should self-register at import time with a single
exported `MANIFEST` symbol:
- _Service_ example: `services/state/<service>/__init__.py`
- _Resource_ example: `resources/substrates/<resource>/__init__.py`

This enables deterministic pre-flight checks and bootstrap orchestration from
the global registry.

------------------------------------------------------------------------
_End of Component Design_
