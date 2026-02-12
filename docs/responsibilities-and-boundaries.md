# Brain -- Responsibility & Boundary Definition
## 1. Purpose
This document defines the authoritative responsibility, ownership, and
boundary model for Brain.

TODO: ENVELOPES EVERYWHERE - WE'LL LOOK LIKE A POST OFFICE

------------------------------------------------------------------------
# 2. Layer Model
One way to think about boundaries within Brain is to think in terms of "Layers"
where humans and LLMs are at the top (Layer 2) while data & integrations are at
the bottom (Layer 0).

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

Data storage Resources are called Substrates. Examples include:
- Obsidian vault
- Postgres

Integration Resources are called Adapters, and are assumed to interact with
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
Another way to think about boundaries within Brian are the three vertically
integrated domains of functionality, or "Systems."

## State System

Responsible for durable data and authority over stateful domains.

Examples: - Vault Authority Service - Memory Authority Service - Object
Authority Service - Cache Authority Service

Responsibilities: - Gate all substrate access - Define domain-specific
invariants - Expose crisply defined ports - Own audit logs for state
mutations

------------------------------------------------------------------------

## Action System

Responsible for "doing" --- executing capabilities and handling external
triggers.

Components:

### Capability Engine

-   Owns Capability registry (Ops and Skills)
-   Executes Capabilities
-   All Capability invocation must pass through this engine
-   Recursively enforces Policy checks for nested Capability calls
-   Owns audit logs for Capability execution

### Policy Engine

-   Owns policy rules
-   Evaluates every Capability invocation
-   Cannot be bypassed by design
-   Owns audit logs for governance decisions

### Switchboard

-   Ingress for external events (Signal, email, etc.)
-   Emits Event Envelopes upward to L2
-   Persists inbound events via Cache Authority (Redis-backed)
-   Buffering is durable but delivery semantics are intentionally
    minimal for now

\[PLACEHOLDER: future refinement of delivery guarantees\]

------------------------------------------------------------------------

## Control System

Responsible for orchestration and scheduling.

-   Scheduler definitions persist via Cache Authority
-   Celery Worker/Beat operate as L2 Actors
-   Scheduled jobs invoke L1 via Brain SDK
-   Control System owns no direct substrate access

------------------------------------------------------------------------

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
