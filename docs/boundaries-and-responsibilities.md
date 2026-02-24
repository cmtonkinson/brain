# Boundaries & Responsibilities
This document defines the coarse boundaries of responsibility and ownership
within Brain.

> Check the [Glossary](glossary.md) for key terms such as _Layer_, _System_, _Resource_,
> _Service_, et cetera.

------------------------------------------------------------------------
## Layer Model
One way to think about boundaries within Brain is to think in terms of
_Layers_, where humans and LLMs are at the top (_Layer_ 2) while data &
integrations are at the bottom (_Layer_ 0).

Invariant: No _Component_ within a given _Layer_ may depend on something from a
higher level.

### Layer 2: Actors
_Actors_ are external clients of _Layer_ 1 _Services_. The Agent process
itself, along with Celery Workers/Beats, and any CLI tooling, are by definition
_Layer_ 2.

The only means for L2/_Actors_ to interact with the system are with the _Brain
Core SDK_, which exposes the _Layer_ 1 _Service_ APIs through gRPC.

L2 has no direct access to L0 _Resources_.

### Layer 1: Services
The system's business logic (and associated public contracts) live in _Layer_ 1.

Properties:
- All _Services_ within L1 are assumed process-local (single container/process)
- _Services_ may call each other directly (but only via _Public APIs_)
- No _Service_ may import another _Service's_ internal implementation
- _Services_ are responsible for their own audit logs, per domain
- _Services_ must enforce relevant policies at _Service_->_Adapter_ boundaries
  where external side effects occur

"East-West" traffic is permitted within L1, but each _Service_ is only permitted
to interact with the formal _Public APIs_ of others. See below for an
explanation of the _System_ Model of _Component_ boundaries.

### Layer 0: Resources
L0 contains persisted data and external integrations. Operations or changes at
_Layer_ 0 either are by definition, or may cause, permanent real world side
effects (sending a message, deleting a file, etc).

Data storage _Resources_ are called _Substrates_. Examples include:
- Obsidian vault
- Postgres

Integration _Resources_ are called _Adapters_, and are assumed to interact with
real-world external systems. Examples include:
- GitHub MCP Server
- Signal CLI

For clarity:
- L0 _Resources_ are ONLY accessible by the appropriate L1 _Services_
  - this is defined on a per _Resource_ basis
  - example: **only** the Vault Authority _Service_ can access Obsidian
  - example: **only** the Capability Engine can access MCP Servers
- L2 has no direct access to L0 whatsoever.

------------------------------------------------------------------------
## System Model
Another way to think about boundaries within Brain are the three vertically-
integrated domains of functionality, or _Systems_. These _Systems_ are composed
of _Services_ which are the main coarse units of Brain logic and functionality.

Within a given _System_, every _Service_ is responsible for:
- Gating all _Resource_ access
- Exposing a crisply defined _Public API_ which is implementation-agnostic with
  respect to the underlying _Resource_
- Defining invariants and access controls
- Owning audit logs for state access & mutation

Policy boundary clarification:
- _Service_->_Service_ calls are internal orchestration and are not policy
  gates by default.
- Policy checks are required at _Service_->_Adapter_ boundaries for external
  side effects.

### State System
The _State System_ is responsible for durable data within Brain. _Services_
within the _State System_ are generally referred to as "Authorities," and each
Authority has access to exactly one _Substrate_, and is the only _Component_
with direct access to that _Substrate_. It's a strict ownership boundary.

Current Authorities:
- **Cache Authority Service** (CAS) owns caching and queueing
- **Embedding Authority Service** (EAS) owns vector search by source/chunk
- **Memory Authority Service** (MAS) owns Agent recall & context management
- **Object Authority Service** (OAS) owns blobs
- **Vault Authority Service** (VAS) owns the Personal Knowledge Base

### Action System
The _Action System_ is responsible for "doing" things with external (real-world)
consequences: consuming and producing signals/triggers/messages, reading and
writing state, and the invocation of such logic.

#### Language Model
- Gates access to Large Language Models
- Exposes both Embedding and Inference capabilities
- Allows config-parameterization of providers, models, version, flags, etc.

#### Capability Engine
- Owns _Capability_ registry (_Ops_ and _Skills_)
- Executes _Capabilities_ pursuant to the Policy Engine
- Recursively enforces Policy checks for nested _Capability_ calls

#### Policy Engine
- Owns Policy rules
- Evaluates every _Capability_ invocation
- Cannot be bypassed (by design - enforced with API limitations and automated
  call site tests)

#### Switchboard
- Responsible for ingress of external events (messages, wake words, etc.)
- Persists inbound events via CAS
- Buffering is durable (delivery semantics are intentionally minimal for now)

#### Attention Router
- Owns outbound access to communication channels with the _Operator_
- Responsible for ensuring disruptions are timely, intentional, and
  non-overloading by deciding to suppress, send, or batch outbounds

### Control System
The _Control System_ is where intentional, custom business logic resides; it's
the "executive function" of the Brain. _Control_ _Services_ exist to leverage
the combination of _State_ and _Action_ _Services_ to achieve higher-order
functionality within the system.

#### Ingestion Pipeline
"Universal Content Ingestion Pipeline": Given an asset (file, link, or other
reference), the Ingestion Pipeline downloads, stores, parses, normalizes,
extracts, and summarizes the data for immediate and/or later use.

The Pipeline has a hooking system so that other _Services_ can register handlers
to be made aware of new content as it is ingested. Raw (as well as some
processed data) is persisted by the OAS, and final outline/summary is stored by
the VAS for human consumption/manipulation.

#### Scheduler/Jobs
Brain must be able to process workloads:
- Once right "now," once "later," or repeatedly on some cadence
- Asynchronously (so they're non-blocking)

Jobs, whether immediate-fire or scheduled, supply a callback for the Job
_Service_ to invoke.

#### Commitment Tracking & Loop Closure
Commitment Tracking & Loop Closure (CTLC) is one of the primary higher-order
functions of Brain. It exists to find and catalogue the _Operator's_ various
commitments, monitor progress/completion against them over time, and escalate
reminders as appropriate to ensure things aren't missed.

------------------------------------------------------------------------
## Shared Infrastructure
The database is a notable exception to the _Services_/_Resources_ Model.
PostgreSQL is a _Layer_ 0 _Substrate_ providing durable, authoritative state,
but is defined (by design decision) as _Shared Infrastructure_. Each L1
_Service_ may access PostgreSQL directly, but for its own schema only.

### Ownership Model
- Each _Service_ has exclusive ownership of its own schema.
- The Postgres schema for a _Service_ is exactly its `ComponentId` (not config).
- _Services_ may only access their own schema.
- Direct cross-schema access (joins, foreign keys) is prohibited. _Services_
  must request foreign records via the _Public API_ of the owning _Service_.
  Referential integrity across _Service_ boundaries is enforced at the API
  layer.
- For convenience, _Services_ use a lightweight wrapper around the connection
  object that sets `search_path` appropriately.

### Primary Key Standard
- All table PKs are ULIDs stored as 16-byte binary.
- Canonical DB type is the schema-local domain: `<schema>.ulid_bin`
  (`ulid_bin` is a constrained `bytea(16)`). Automated tests will fail if
  violations are found.
- ULIDs are generated in application code, never in Postgres.
- Shared helpers are in `packages/brain_shared/ids/` (backed by `python-ulid`).

### Migrations
Each _Service_ maintains an isolated Alembic environment (its own `.ini`,
`env.py`, `versions/`, etc.). A wrapper utility runs migrations in a consistent
order (_State_, then _Action_, then _Control_). This isn't strictly necessary
given cross-_Service_ FKs are disallowed, however does provide deterministic
bootstrapping.

`make migrate` will automatically, for every valid, registered _Service_:
1. Import self-registering _Component_ modules (`*/component.py`).
2. Validate _Manifest_ registry ownership/invariants.
3. For each registered _Service_ schema:
   - create schema if missing (name derived from `component_id`, e.g. the EAS
     `component_id` is `service_embedding_authority`)
   - create `<schema>.ulid_bin` domain if missing
4. Run Alembic migrations in _System_-order (`state` -> `action` -> `control`).

### Contributor Checklist (New Service)
1. Add `services/<system>/<service>/component.py` with `ServiceManifest`.
2. Keep schema identity derived from `ComponentId`.
3. Use shared ULID PK helpers that target `<schema>.ulid_bin`.
4. Keep migrations in that _Service's_ own Alembic environment only.
5. Never query/mutate other _Service_ schemas directly.
6. Keep service configuration and typed boundary contracts aligned with
   Pydantic usage rules in [Conventions](conventions.md).

For communication rules, wire protocols, error handling, SDKs, and other
behavioral conventions, see [Conventions](conventions.md).

------------------------------------------------------------------------
_End of Boundaries & Responsibilities_
