# Boundaries & Responsibilities
This document defines the coarse boundaries of responsibility and ownership
within Brain.

> Check the [Glossary](glossary.md) for key terms such as _Tier_, _Plane_,
> _Service_, _Resource_, _Provider_, et cetera.

------------------------------------------------------------------------
## Tier Model
One way to think about boundaries within Brain is to think in terms of
_Tiers_, where humans and LLMs are at the top (_Tier_ 3) while data &
integrations are at the bottom (_Tier_ 1).

Invariant: No _Component_ within a given _Tier_ may depend on something from a
higher level.

### Tier 3: Actors
_Actors_ are external clients of _Tier_ 2 _Services_. The Assistant, Subagent,
Worker, Console, and CLI processes are by definition _Tier_ 3.

The only means for T3/_Actors_ to interact with the system are with the _Brain
Core SDK_, which exposes a published subset of _Tier_ 2 _Service_ APIs through
the Core HTTP surface. That published surface is not required to be one-to-one
with each _Service's_ _Public API_; some _Public API_ methods may remain
internal-only.

T3 has no direct access to T1 _Resources_.

### Tier 2: Services
The system's business logic (and associated public contracts) live in _Tier_ 2.

Properties:
- All _Services_ within T2 are assumed process-local (single container/process)
- _Services_ may call each other directly (but only via _Public APIs_)
- No _Service_ may import another _Service's_ internal implementation
- _Services_ are responsible for their own audit logs, per domain
- _Services_ must enforce relevant policies at _Service_->_Adapter_ boundaries
  where external side effects occur

"East-West" traffic is permitted within T2, but each _Service_ is only permitted
to interact with the formal _Public APIs_ of others. See below for an
explanation of the _Plane_ Model of _Component_ boundaries.

### Tier 1: Resources
T1 contains persisted data and external integrations. Operations or changes at
_Tier_ 1 either are by definition, or may cause, permanent real world side
effects (sending a message, deleting a file, etc).

_Resources_ are Brain-facing interfaces over lower-level _Providers_. A
_Provider_ is the concrete backing surface a _Resource_ governs, such as an
isolated Docker service/container, a host process, a host directory/file, or a
third-party WAN API.

**Storage** _Resources_ are called _Substrates_. Examples include:
- Obsidian vault
- Postgres

**Integration** _Resources_ are called _Adapters_, and are assumed to interact
with real-world external systems. Examples include:
- GitHub MCP Server
- Signal CLI

For clarity:
- T1 _Resources_ are ONLY accessible by the appropriate T2 _Services_
  - this is defined on a per-_Resource_ basis
  - example: **only** the Vault _Service_ can access Obsidian
  - example: **only** the Execution _Service_ can access MCP Servers
  - example: **only** the Relay _Service_ can access the Signal Adapter
- T3 has no direct access to T1 whatsoever.

------------------------------------------------------------------------
## Plane Model
Another way to think about boundaries within Brain are the three vertically-
integrated domains of functionality, or _Planes_. These _Planes_ are composed
of _Services_ which are the main coarse units of Brain logic and functionality.

Within a given _Plane_, every _Service_ is responsible for:
- Gating all _Resource_ access
- Exposing a crisply defined _Public API_ which is, where possible,
  implementation-agnostic with respect to the underlying _Resource_ and
  _Provider_
- Defining invariants and access controls
- Owning audit logs for state access & mutation

Policy boundary clarification:
- _Service_->_Service_ calls are internal orchestration and are not policy
  gates by default.
- Policy checks are required at _Service_->_Adapter_ boundaries for external
  side effects.

### Placement Rule (Resource-Ownership Invariant)
Every T2 _Service_ is placed by the shape of its _Resource_ ownership:

| Service owns... | belongs in Plane |
|---|---|
| a Substrate | **State** |
| an Adapter | **Effect** |
| no Resource | **Reason** |

This is enforced at manifest-registration time. A _Service_ may not own both
a Substrate and an Adapter.

### State Plane
The _State Plane_ is responsible for durable data within Brain. Each
_Service_ in this _Plane_ owns exactly one _Substrate_ and is the only
_Component_ with direct access to it. Strict custody boundary.

Current State _Services_:
- **Cache** owns caching and queueing
- **Embedding** owns vector search by source/chunk
- **Object** owns blobs
- **Vault** owns the Personal Knowledge Base

### Effect Plane
The _Effect Plane_ is responsible for actions with external (real-world)
consequences: consuming and producing signals/triggers/messages, gating
real-world side effects, and the invocation of such logic. Each _Service_
in this _Plane_ owns exactly one _Adapter_.

#### Language
- Gates access to Large Languages
- Exposes both Embedding and Inference ops
- Allows config-parameterization of providers, models, version, flags, etc.

#### Execution
- Owns _Op_ registry
- Executes _Ops_ pursuant to the Policy
- Recursively enforces Policy checks for nested _Op_ calls

#### Relay
- Owns the bidirectional operator-comms channel (currently the Signal
  adapter; future channels slot in here)
- Inbound: ingests external events (messages, wake words, console input),
  persists buffered queues via Cache
- Outbound: ensures disruptions are timely, intentional, and
  non-overloading by deciding to suppress, send, or batch outbounds
- Approval round-trip: correlates outbound approval prompts with inbound
  replies inside one service

### Reason Plane
The _Reason Plane_ is where intentional, custom business logic resides;
it's the "executive function" of the Brain. _Reason_ _Services_ own no
external _Resource_; they leverage the combination of _State_ and _Effect_
_Services_ to achieve higher-order functionality.

#### Policy
- Owns Policy rules
- Evaluates every _Op_ invocation
- Cannot be bypassed (by design - enforced with API limitations and automated
  call site tests)

#### Recall
- Owns Assistant recall & context management over Embedding/Vault/Object results
- No dedicated Substrate; composes State Plane data into context windows

#### Utility
- Lightweight reusable helper operations

#### Ingestion Pipeline
"Universal Content Ingestion Pipeline": Given an asset (file, link, or other
reference), the Ingestion Pipeline downloads, stores, parses, normalizes,
extracts, and summarizes the data for immediate and/or later use.

The Pipeline has a hooking system so that other _Services_ can register handlers
to be made aware of new content as it is ingested. Raw (as well as some
processed data) is persisted by the Object Service, and final outline/summary
is stored by the Vault Service for human consumption/manipulation.

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

#### Delegation
- Owns subagent invocation lifecycle: queue, claim, status, transcripts,
  budget ledger, cancel
- No dedicated Substrate; composes Language inference and Execution op calls
  into a higher-order "spawn a focused subagent" capability
- Backed by a dedicated T3 actor (`actors/subagent`) that drains the claim
  queue and runs the headless tool loop in `lib/agent`

------------------------------------------------------------------------
## Shared Infrastructure
The database is a notable exception to the _Services_/_Resources_ Model.
PostgreSQL is a _Tier_ 1 _Substrate_ providing durable, authoritative state,
but is defined (by design decision) as _Shared Infrastructure_. Each T2
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
- Shared helpers are in `lib/shared/ids/` (backed by `python-ulid`).

### Migrations
Each _Service_ maintains an isolated Alembic environment (its own `.ini`,
`env.py`, `versions/`, etc.). A wrapper utility runs migrations in a consistent
order (_State_, then _Effect_, then _Reason_). This isn't strictly necessary
given cross-_Service_ FKs are disallowed, however does provide deterministic
bootstrapping.

During Core boot, the migration wrapper automatically, for every valid,
registered _Service_:
1. Import self-registering _Component_ modules (`*/component.py`).
2. Validate _Manifest_ registry ownership/invariants.
3. For each registered _Service_ schema:
   - create schema if missing (name derived from `component_id`, e.g. the Embedding
     `component_id` is `service_embedding`)
   - create `<schema>.ulid_bin` domain if missing
4. Run Alembic migrations in _Plane_-order (`state` -> `effect` -> `reason`).

### Contributor Checklist (New Service)
1. Add `services/<plane>/<service>/component.py` with `ServiceManifest`.
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
