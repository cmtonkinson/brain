# Responsibility & Boundary Definitions
## 1. Purpose
This document defines the authoritative responsibility, ownership, and
boundary model for Brain.

------------------------------------------------------------------------
# 2. Layer Model
One way to think about boundaries within Brain is to think in terms of
**Layers**, where humans and LLMs are at the top (Layer 2) while data &
integrations are at the bottom (Layer 0).

Invariant: No component within a given layer may depend on something from a
higher level.

## Layer 2: Actors
Actors are external clients of Layer 1 services. The Agent process itself, along
with Celery Workers/Beats, and any CLI tooling, are by definition Layer 2.

The only means for L2/Actors to interact with the system are with the Brain SDK,
which exposes the Layer 1 Service APIs through gRPC.

L2 has no direct access to L0 Resources.

## Layer 1: Services
The system's business logic (and associated public contracts) live in Layer 1.

Properties:
- All Services within L1 are assumed process-local (single container/process)
- Services may call each other directly (but only via public APIs)
- No service may import another service's internal implementation
- Services are reponsible for their own audit logs, per domain
- Services must enforce relevant policies

"East-West" traffic is permitted within L1, but each Service is only permitted
to interact with the formal public APIs of others. See below for an explanation
of the System Model of component boundaries.

## Layer 0: Resources
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

------------------------------------------------------------------------
# Public APIs
TL;DR &mdash; Package-versioned protobufs w/ gRPC

Each L1 Service must define a public API via a `.proto`. These public APIs:
- Are the canonical and authoritative (Python) interface to the Service
- Versioned at the package level (e.g. `serv_a.v1`, `serv_b.v3`)
- The sole permitted surface for cross-Service calls
- Define method signatures using envelope-like request/response messages
- Describe their Error taxonomy via gRPC status codes and typed structured
  errors

Protobuf interfaces are exposed to L2 across network boundaries via gRPC over
Unix domain sockets. Removed fields must be marked `reserved` while breaking
changes require a new package version (v1 → v2). 

Protos live in `protos/`, Python is regenerated on build, git-ignored, and lives
in `generated/`, while `services/` holds implementations.

------------------------------------------------------------------------
# Envelopes
All cross-Layer and cross-Service communication must use Envelopes. An Envelope
consists of:
- Metadata
- Payload
- Errors

### gRPC API Typing Note
For protobuf/gRPC compile-time type enforcement, Service APIs should generally
use operation-specific request/response messages that are envelope-like
(`metadata`, typed `payload`, and `errors` where applicable), rather than a
single polymorphic wire-envelope type at every RPC boundary.

### Envelope Kinds
**Command Envelope:** Generated by L2 for Capability invocation.  
**Event Envelope:** Generated by L1 upon external or system-triggered activity.  
**Result Envelope:** Used for responses to other Enveloped messages.
**Stream Envelope:** \[TODO\]/reserved - future real-time streaming support.

### Metadata (Structured)
- `envelope_id`: _required_ ULID
- `trace_id`: _required_ ULID
- `parent_id`: _optional_ ULID
- `timestamp`: _required_ int64
- `kind`: _required_ string (one of `command`, `event`, `result`, `stream`)
- `source`: _required_ string (e.g. `cli`, `agent`, `switchboard`, `job`)
- `principal`: _required_ string (e.g. `operator`, `ctlc`, `core`)

Envelope subclasses may append their own metadata. For clarity, `source` is the
immediate emitting component for _"this" specific Envelope_, whereas `principal`
is the accountable identity (effective authority) for the request. Components
are required to propogate `principal` unchanged across calls.

**Illustrative (non-literal) example:**  
The Operator requests a reminder in 1 hour. A message is passed from the
Switchboard to the Agent like:
  - `source = "switchboard"`
  - `principal = "operator"`
which results in a message from the Agent to the Scheduler like:
  - `source = "agent"`
  - `principal = "operator"`

An hour later, the schedule fires and the Job invokes the Agent like:
  - `source = "job"`
  - `principal = "operator"`
which results in a message from the Agent to the Attention Router like:
  - `source = "agent"`
  - `principal = "operator"`

### Tracing
A `trace_id` scopes a single execution episode. In the example above, the first
two Envelopes share the same `trace_id`. The third and fourth share a new
`trace_id` (distinct from the first two), and the third sets `parent_id` to the
`envelope_id` of the scheduling Envelope from the prior trace.

This keeps each execution episode independently observable while preserving
cross-trace causality for long-term lineage and analysis. This provides for a
DAG of Envelopes across time, with trace segments as execution partitions.

### Payload
Domain-specific content.

> You can use these oats to make oatmeal, bread, whatever you want. I don't
> care, they're your oats.
> &mdash; Dwight K. Schrute

### Errors
Most usually Errors will be present in a Result Envelope, but are not invalid in
any Envelope. Errors are a collection of structured objects representing some
failure mode/state.

------------------------------------------------------------------------
# Principal Identity Model
The **Principal** is "who the system treats as accountable" for a given request.

**`operator`** - All "personal assistant" work should utlimately roll up to the
Operator.

**`<service>`** (e.g. `switchboard`, `ctlc`) - This represents a Layer 1 Service
acting autonomously. This is used when Serivces initiate work without an
immediate upstream request (think scheduled jobs, inbound interrupt, etc.)

**`core`** - Rare. Only used for truly low-level, cross-cutting "infrastructure"
behavior which are explicitly system-meta in nature.

------------------------------------------------------------------------
# SDKs
## Brain SDK
The Brain SDK is the public interface for L2 Actors of Brain Core using
Protobuf/gRPC. All L2 Actors must be built on the Brain SDK.

The SDK contains no business logic; it simply exists as an access layer across
network boundaries to the pulic L1 Servie APIs.

## Capability SDK
The Capability SDK supports registration and management of Capabilities (Ops and
Skills) including both logic and metadata such as Policy declarations.

------------------------------------------------------------------------
# Error Taxonomy
Errors must be categorized as:
- terminal
- retriable

Errors may carry optional category fields such as:
- conflict
- dependency
- not_found
- policy
- validation

Policy violations are, by definition, terminal, and should not be retried.

## Transport vs Domain Failure Mapping
To avoid ambiguity at service boundaries:
- **Domain failures** (validation, conflict, not_found, policy) are returned as
  typed structured errors in the envelope-like response.
- **Transport/infrastructure failures** (dependency unavailable, internal
  runtime faults) are surfaced as transport failures on gRPC status codes.

This keeps domain behavior explicit and machine-readable while preserving normal
transport semantics for network/runtime outages.

------------------------------------------------------------------------
# Policy Enforcement Rule
All Capability invocations (including within Skills) MUST pass through
Capability Engine invoke(). Skills must not directly call other Skills or Ops by
importing implementations. Policy Engine evaluation is mandatory and recursive.

------------------------------------------------------------------------
# Process Assumptions
- L2 Actors are process-and-network isolated
- L1 Services are process-local, but restricted to public APIs
- L0 Substrates and Adapters are non-local

------------------------------------------------------------------------
_End of Responsibilities and Boundaries_ 
