# Core Startup Sequence
This document defines the canonical initialization sequence for Brain Core. It
exists to make startup behavior explicit, deterministic, and reviewable.

## Goals
- Avoid partial or invalid runtime state at process startup.
- Ensure migrations complete before any runtime object can touch service tables.
- Preserve a deterministic boot contract across components.
- Keep component wiring driven by manifest registry metadata, not hardcoded startup lists.

## Canonical Order
1. **Load settings**
   - Resolve config from file/env/overrides into typed settings.

2. **Discover and register components**
   - Import component declaration modules.
   - Materialize the process-local registry.
   - Validate manifest invariants and ownership relationships.

3. **Run schema bootstrap + migrations**
   - Provision service schemas/primitives.
   - Execute service migrations in system order.
   - This step must finish before component instantiation.

4. **Instantiate components from registry graph**
   - Build L0 _Resources_ and L1 _Services_ via per-component builders.
   - Resolve dependencies using registry-declared relationships.
   - Fail hard on unresolved dependency graphs.

5. **Run boot orchestration**
   - Phase A: global readiness gate (all boot hooks must report ready).
   - Phase B: execute `boot()` in DAG/topological dependency order.

6. **Load capabilities**
   - Discover and register capability packages.
   - Perform capability validation after boot so boot-established runtime state is available.

7. **Run `after_boot(...)` lifecycle hooks**
   - Execute optional component-level `after_boot` hooks.
   - Run after global boot/capability startup work and before serving gRPC.
   - Fail hard if any `after_boot` hook raises.

8. **Start gRPC runtime**
   - Construct gRPC server.
   - Register service adapters/handlers.
   - Bind listeners and begin serving.

9. **Enter process hold loop**
   - Keep process alive.
   - Handle shutdown signals for clean termination.

## Why This Order
- **Migrations before instantiation** prevents constructors from touching missing tables.
- **Global readiness before any boot action** prevents partial boot side effects.
- **Capabilities after boot** allows dependencies like MCP and boot-generated runtime state to be available before capability discovery/validation.
- **after_boot before gRPC** ensures post-boot initialization completes before external traffic is accepted.
- **gRPC last** ensures external traffic is accepted only after startup is complete.

## Non-Goals (Current Phase)
- This sequence does not require every `is_ready` hook to be deep/strict yet; some hooks may be no-op while implementation matures.
- This sequence definition does not mandate specific deployment topology (single process vs split runtime) as long as ordering guarantees hold.

------------------------------------------------------------------------
_End of Core Startup Sequence_
