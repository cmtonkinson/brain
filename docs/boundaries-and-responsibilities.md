# Boundaries & Responsibilities
This document defines the coarse boundaries of responsibility and ownership
within Brain.

> Check the [Glossary](glossary.md) for key terms such as *Tier*, *Plane*,
> *Service*, *Resource*, *Provider*, et cetera.

------------------------------------------------------------------------
## Tier Model
One way to think about boundaries within Brain is to think in terms of
*Tiers*, where humans and LLMs are at the top (*Tier* 3) while data &
integrations are at the bottom (*Tier* 1).

Invariant: No *Component* within a given *Tier* may depend on something from a
higher level.

### Tier 3: Actors
*Actors* are external clients of *Tier* 2 *Services*. The Assistant, Subagent,
Worker, Console, and CLI processes are by definition *Tier* 3.

The only means for T3/*Actors* to interact with the system are with the _Brain
Core SDK_, which exposes a published subset of *Tier* 2 *Service* APIs through
the Core HTTP surface. That published surface is not required to be one-to-one
with each *Service's* *Public API*; some *Public API* methods may remain
internal-only.

T3 has no direct access to T1 *Resources*.

### Tier 2: Services
The system's business logic (and associated public contracts) live in *Tier* 2.

Properties:
* All *Services* within T2 are assumed process-local (single container/process)
* *Services* may call each other directly (but only via *Public APIs*)
* No *Service* may import another *Service's* internal implementation
* *Services* are responsible for their own audit logs, per domain
* *Services* must enforce relevant policies at *Service*->*Adapter* boundaries
  where external side effects occur

"East-West" traffic is permitted within T2, but each *Service* is only permitted
to interact with the formal *Public APIs* of others. See below for an
explanation of the *Plane* Model of *Component* boundaries.

### Tier 1: Resources
T1 contains persisted data and external integrations. Operations or changes at
*Tier* 1 either are by definition, or may cause, permanent real world side
effects (sending a message, deleting a file, etc).

*Resources* are Brain-facing interfaces over lower-level *Providers*. A
*Provider* is the concrete backing surface a *Resource* governs, such as an
isolated Docker service/container, a host process, a host directory/file, or a
third-party WAN API.

**Storage** *Resources* are called *Substrates*. Examples include:
* Obsidian vault
* Postgres

**Integration** *Resources* are called *Adapters*, and are assumed to interact
with real-world external systems. Examples include:
* GitHub MCP Server
* Signal CLI

For clarity:
* T1 *Resources* are ONLY accessible by the appropriate T2 *Services*
  * this is defined on a per-*Resource* basis
  * example: **only** the Vault *Service* can access Obsidian
  * example: **only** the Execution *Service* can access MCP Servers
  * example: **only** the Relay *Service* can access the Signal Adapter
* T3 has no direct access to T1 whatsoever.

------------------------------------------------------------------------
## Plane Model
Another way to think about boundaries within Brain are the three vertically-
integrated domains of functionality, or *Planes*. These *Planes* are composed
of *Services* which are the main coarse units of Brain logic and functionality.

Within a given *Plane*, every *Service* is responsible for:
* Gating all *Resource* access
* Exposing a crisply defined *Public API* which is, where possible,
  implementation-agnostic with respect to the underlying *Resource* and
  *Provider*
* Defining invariants and access controls
* Owning audit logs for state access & mutation

Policy boundary clarification:
* *Service*->*Service* calls are internal orchestration and are not policy
  gates by default.
* Policy checks are required at *Service*->*Adapter* boundaries for external
  side effects.

### Placement Rule (Resource-Ownership Invariant)
Every T2 *Service* is placed by the shape of its *Resource* ownership:

| Service owns... | belongs in Plane |
|---|---|
| a Substrate | **State** |
| an Adapter | **Effect** |
| no Resource | **Reason** |

This is enforced at manifest-registration time. A *Service* may not own both
a Substrate and an Adapter.

### State Plane
The *State Plane* is responsible for durable data within Brain. Each
*Service* in this *Plane* owns exactly one *Substrate* and is the only
*Component* with direct access to it. Strict custody boundary.

Current State *Services*:
* **Cache** owns caching and queueing
* **Embedding** owns vector search by source/chunk
* **Object** owns blobs
* **Vault** owns the Personal Knowledge Base

### Effect Plane
The *Effect Plane* is responsible for actions with external (real-world)
consequences: consuming and producing signals/triggers/messages, gating
real-world side effects, and the invocation of such logic. Each *Service*
in this *Plane* owns exactly one *Adapter*.

#### Language
* Gates access to Large Languages
* Exposes both Embedding and Inference ops
* Allows config-parameterization of providers, models, version, flags, etc.

#### Execution
* Owns *Op* registry
* Executes *Ops* pursuant to the Policy
* Recursively enforces Policy checks for nested *Op* calls

#### Relay
* Owns the bidirectional operator-comms channel (currently the Signal
  adapter; future channels slot in here)
* Inbound: ingests external events (messages, wake words, console input),
  persists buffered queues via Cache
* Outbound: ensures disruptions are timely, intentional, and
  non-overloading by deciding to suppress, send, or batch outbounds
* Approval round-trip: correlates outbound approval prompts with inbound
  replies inside one service

### Reason Plane
The *Reason Plane* is where intentional, custom business logic resides;
it's the "executive function" of the Brain. *Reason* *Services* own no
external *Resource*; they leverage the combination of *State* and *Effect*
*Services* to achieve higher-order functionality.

#### Policy
* Owns Policy rules
* Evaluates every *Op* invocation
* Cannot be bypassed (by design - enforced with API limitations and automated
  call site tests)

#### Recall
* Owns Assistant recall & context management over Embedding/Vault/Object results
* No dedicated Substrate; composes State Plane data into context windows

#### Utility
* Lightweight reusable helper operations

#### Ingestion Pipeline
"Universal Content Ingestion Pipeline": Given an asset (file, link, or other
reference), the Ingestion Pipeline downloads, stores, parses, normalizes,
extracts, and summarizes the data for immediate and/or later use.

The Pipeline has a hooking system so that other *Services* can register handlers
to be made aware of new content as it is ingested. Raw (as well as some
processed data) is persisted by the Object Service, and final outline/summary
is stored by the Vault Service for human consumption/manipulation.

#### Scheduler/Jobs
Brain must be able to process workloads:
* Once right "now," once "later," or repeatedly on some cadence
* Asynchronously (so they're non-blocking)

Jobs, whether immediate-fire or scheduled, supply a callback for the Job
*Service* to invoke.

#### Commitment Tracking & Loop Closure
Commitment Tracking & Loop Closure (CTLC) is one of the primary higher-order
functions of Brain. It exists to find and catalogue the *Operator's* various
commitments, monitor progress/completion against them over time, and escalate
reminders as appropriate to ensure things aren't missed.

#### Delegation
* Owns subagent invocation lifecycle: queue, claim, status, transcripts,
  budget ledger, cancel
* No dedicated Substrate; composes Language inference and Execution op calls
  into a higher-order "spawn a focused subagent" capability
* Backed by a dedicated T3 actor (`actors/subagent`) that drains the claim
  queue and runs the headless tool loop in `lib/agent`

------------------------------------------------------------------------
## Shared Infrastructure
The database is a notable exception to the *Services*/*Resources* Model.
PostgreSQL is a *Tier* 1 *Substrate* providing durable, authoritative state,
but is defined (by design decision) as *Shared Infrastructure*. Each T2
*Service* may access PostgreSQL directly, but for its own schema only.

### Ownership Model
* Each *Service* has exclusive ownership of its own schema.
* The Postgres schema for a *Service* is exactly its `ComponentId` (not config).
* *Services* may only access their own schema.
* Direct cross-schema access (joins, foreign keys) is prohibited. *Services*
  must request foreign records via the *Public API* of the owning *Service*.
  Referential integrity across *Service* boundaries is enforced at the API
  layer.
* For convenience, *Services* use a lightweight wrapper around the connection
  object that sets `search_path` appropriately.

### Primary Key Standard
* All table PKs are ULIDs stored as 16-byte binary.
* Canonical DB type is the schema-local domain: `<schema>.ulid_bin`
  (`ulid_bin` is a constrained `bytea(16)`). Automated tests will fail if
  violations are found.
* ULIDs are generated in application code, never in Postgres.
* Shared helpers are in `lib/shared/ids/` (backed by `python-ulid`).

### Migrations
Each *Service* maintains an isolated Alembic environment (its own `.ini`,
`env.py`, `versions/`, etc.). A wrapper utility runs migrations in a consistent
order (*State*, then *Effect*, then *Reason*). This isn't strictly necessary
given cross-*Service* FKs are disallowed, however does provide deterministic
bootstrapping.

During Core boot, the migration wrapper automatically, for every valid,
registered *Service*:
1. Import self-registering *Component* modules (`*/component.py`).
2. Validate *Manifest* registry ownership/invariants.
3. For each registered *Service* schema:
   * create schema if missing (name derived from `component_id`, e.g. the Embedding
     `component_id` is `service_embedding`)
   * create `<schema>.ulid_bin` domain if missing
4. Run Alembic migrations in *Plane*-order (`state` -> `effect` -> `reason`).

### Contributor Checklist (New Service)
1. Add `services/<plane>/<service>/component.py` with `ServiceManifest`.
2. Keep schema identity derived from `ComponentId`.
3. Use shared ULID PK helpers that target `<schema>.ulid_bin`.
4. Keep migrations in that *Service's* own Alembic environment only.
5. Never query/mutate other *Service* schemas directly.
6. Keep service configuration and typed boundary contracts aligned with
   Pydantic usage rules in [Conventions](conventions.md).

For communication rules, wire protocols, error handling, SDKs, and other
behavioral conventions, see [Conventions](conventions.md).


------------------------------------------------------------------------
_End of Boundaries & Responsibilities_
