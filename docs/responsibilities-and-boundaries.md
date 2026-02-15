# Brain -- Responsibility & Boundary Definition
## 1. Purpose
This document defines the authoritative responsibility, ownership, and
boundary model for Brain.

TODO: ENVELOPES EVERYWHERE - WE'LL LOOK LIKE A POST OFFICE

------------------------------------------------------------------------
# 2. Layer Model
One way to think about boundaries within Brain is to think in terms of
**Layers**, where humans and LLMs are at the top (Layer 2) while data &
integrations are at the bottom (Layer 0).

Invariant: No component within a given layer may depend on something from a
higher level.

## Layer 2 -- Actors
Actors are external clients of Layer 1 services. The Agent process itself, along
with Celery Workers/Beats, and any CLI tooling, are by definition Layer 2.

The only means for L2/Actors to interact with the system are with the Brain SDK,
which exposes the Layer 1 Service APIs through gRPC.

L2 has no direct access to L0 Resources.

## Layer 1 -- Services
The system's business logic (and associated public contracts) live in Layer 1.

Properties:
- All Services within L1 are assumed process-local (single container/process)
- Services may call each other directly (but only via public APIs)
- No service may import another service's internal implementation
- Services are reponsible for their own audit logs, per domain
- Services must enforce relevant policies

Limited "East-West" traffic is permitted within L1, subject to System dependency
rules (see below for an explanation of the System Model).

## Layer 0 -- Resources
L0 contains persisted data and external integrations. Operations or changes at
Layer 0 either are by definition, or may cause, permanent real world side
effects (sending a message, deleting a file, etc).

Data storage Resources are called **Substrates**. Examples include:
- Obsidian vault
- Postgres

Integration Resources are called **Adapters**, and are assumed to interact with
real-world external systems. Examples include:
- GitHub MCP Server
- Signal CLI

For clarity:
- L0 Resources are ONLY accessible by the appropriate L1 Services
  - this is defined on a per Resource basis
  - example: **only** the Vault Authority Service can access Obisidian
  - example: **only** the Capability Engine can access MCP Servers
- L2 has no direct access to L0 whatsoever.

------------------------------------------------------------------------
# 3. System Model
Another way to think about boundaries within Brian are the three vertically-
integrated domains of functionality, or **Systems**. These Systems are composed
of **Services** which are the main coarse units of Brain logic and functionality.

Within a given System, every Service is responsible for:
- Gating all Resource access
- Exposing a crisply defined public API which is implementation-agnostic with
  respect to the underlying Resource
- Defining invariants and access controls
- Owning audit logs for state access & mutation

## State System
The State System is responsible for durable data within Brain. Services within
the State System are generally referred to as "Authorities," and each Authority
has access to exactly one Substrate, and is the only component with direct
access to that substrate. It's a strict owndership boundary.

Current Authorities:
- **Vault Authority Service** (VAS) owns the Personal Knowledge Base 
- **Cache Authority Service** (CAS) owns caching and queueing
- **Object Authority Service** (OAS) owns blobs
- **Memory Authority Service** (MAS) owns Agent recall & context management

## Action System
The Action System is responsible for "doing" things with external (real-world)
consequences: consuming and producing signals/triggers/messages, reading and
writing state, and the invocation of such logic.

### Capability Engine
- Owns Capability registry (Ops and Skills)
- Executes Capabilities pursuant to the Policy Engine
- Recursively enforces Policy checks for nested Capability calls

### Policy Engine
- Owns Policy rules
- Evaluates every Capability invocation
- Cannot be bypassed (by design - enforced with API limitations and automated
  call site tests)

### Switchboard
- Responsible for ingress of external events (messages, wake words, etc.)
- Persists inbound events via CAS
- Buffering is durable (delivery semantics are intentionally minimal for now)

### Attention Router
- Owns outbound access to communication channels with the Operator
- Responsible for ensuring disruptions are timely, intentional, and
  non-overloading by deciding to suppress, send, or batch outbounds

## Control System
The Control System is where intentional, custom business logic resides; it's
the "executive function" of the Brain. Control Services exist to leverage the
combination of State and Action Services to achieve higher-order functionality
within the system.

### Ingestion Pipeline
"Universal Content Ingestion Pipeline": Given an asset (file, link, or other
reference), the Ingestion Pipeline downloads, stores, parses, normalizes,
extracts, and summarizes the data for immediate and/or later use.

The Pipeline has a hooking system so that other Services can register handlers
to be made aware of new content as it is ingested. Raw (as well as some
processed data) is persisted by the OAS, and final outline/summary is stored by
the VAS for human consumption/manipulation.

### Scheduler/Jobs
Brain must be able to process workloads:
- Once right "now," once "later," or repeatedly on some cadence
- Asynchronously (so they're non-blocking)

Jobs, whether immediate-fire or scheduled, supply a callback for the Job
Service to invoke. 

### Committment Tracking & Loop Closure
Committment Tracking & Loop Closure (CTLC) is one of the primary higher-order
functions of Brain. It exists to find and catalogue the Operators various
committments, monitor progress/completion against them over time, and escalate
reminders as appropriate to ensure things aren't missed.

------------------------------------------------------------------------
# Shared Infrastructure 
The database is a notable exception to the Services Model with respect to
storage. PostgreSQL is a Layer 0 Resource providing durable, authoritative
state, but is defined (by design decision) as _Shared Infrastructure_. Each L1
Service may access PostgreSQL directly for its own schema only.

To do this cleanly, it means:
- Each Service has exclusive ownership of its own schema.
- Direct cross-schema access is prohibited. Services must request foreign
  records via the public API of the owning Service.
- Cross-service foreign keys are prohibited; referential integrity across
  Service boundaries is enforced at the API layer.
- For convenience, Services use a lightweight wrapper around the connection
  object that sets `search_path` appropriately.
- Each Service maintains an isolated Alembic environment (its own `.ini`,
  `env.py`, `versions/`, etc.).
- A wrapper utility runs migrations in a consistent order (e.g., first State,
  then Action, then Control). This isn't strictly necessary given cross-Service
  FKs are disallowed, however does provide deterministic bootstrapping.

# 4. Ports

Each L1 Service must define a public Port.

A Port is: - The canonical Python interface (authoritative) - Versioned
via SemVer - The sole permitted surface for cross-service calls

Ports define: - Method signatures - Input/Output envelope types - Error
taxonomy contract

Protobuf / gRPC surfaces are derived from Python ports.

Proto artifacts must not be manually edited.

\[PLACEHOLDER: generation pipeline details\]

------------------------------------------------------------------------

# 5. SDKs

## Brain SDK

-   Defines gRPC transport over all L1 service ports
-   Used by L2 Actors
-   Must not contain business logic
-   Acts as client façade over service ports

## Capability SDK

-   Supports registration and management of Ops and Skills
-   Defines Capability metadata schema
-   Interacts with Capability Engine registry

------------------------------------------------------------------------

# 6. Envelopes

All cross-layer communication must use Envelopes.

## Envelope Structure

An Envelope consists of:

-   Metadata
-   Payload
-   Errors (optional collection)

### Metadata (Structured)

Minimum required: - correlation_id

Optional: - principal \[PLACEHOLDER\] - causation_id \[PLACEHOLDER\] -
timestamp \[PLACEHOLDER\] - category \[PLACEHOLDER\]

### Payload

Domain-specific content.

### Errors

Structured error objects adhering to taxonomy.

------------------------------------------------------------------------

## Envelope Types

### Command Envelope (L2 → L1)

Used for Capability invocation.

### Event Envelope (L1 → L2)

Used for external or system-triggered notifications.

### Result Envelope (L1 → L2)

Used for responses to Commands.

### Stream Envelope \[TODO\]

Future real-time streaming support.

------------------------------------------------------------------------

# 7. Error Taxonomy

Errors must be categorized as:

-   terminal
-   retriable

Optional category field may include: - policy - validation -
dependency - not_found - conflict

Policy violations are terminal by definition.

------------------------------------------------------------------------

# 8. Versioning

All Service Ports adhere to SemVer.

Breaking changes include: - Signature change - Envelope schema change -
Removal of error category - Change in behavioral contract

Envelope schema versioning rules: - Additive changes allowed in minor
versions - Removals only in major versions

\[QUESTION: should Envelope schema version be independent of service
version?\]

------------------------------------------------------------------------

# 9. Authority Gating

Only Authority Services may access Substrate.

Examples: - Obsidian access via Vault Authority - Letta via Memory
Authority - Object store via Object Authority - Redis via Cache
Authority - Signal via Switchboard

Direct substrate access outside designated authority is prohibited.

------------------------------------------------------------------------

# 10. Policy Enforcement Rule

All Capability invocations must pass through Capability Engine invoke().
Skills must not directly call other Skills or Ops by importing
implementations. Policy Engine evaluation is mandatory and recursive.

------------------------------------------------------------------------

# 11. Process Assumptions

-   L1 services are process-local but restricted to ports
-   L2 actors are process and network isolated
-   L0 substrate and adapters are non-local

------------------------------------------------------------------------

# 12. Open Items

\[PLACEHOLDER: Session/Conversation handle lifecycle for voice\]

\[PLACEHOLDER: Principal identity model\]

\[PLACEHOLDER: gRPC generation pipeline specifics\]

\[PLACEHOLDER: Future delivery semantics refinement\]

------------------------------------------------------------------------

End of Document
