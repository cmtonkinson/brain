# Brain -- Responsibility & Boundary Definition

## 1. Purpose

This document defines the authoritative responsibility, ownership, and
boundary model for Brain. It is ontological and normative. Refactoring
and implementation must conform to this definition.

This document is supplemental to C4 Context, Container, and Component
diagrams.

------------------------------------------------------------------------

# 2. Layer Model

Brain is structured into three layers.

## Layer 2 (L2) -- Actors

Actors are external clients of Layer 1 services.

Examples: - CLI - TUI - Agent runtime - Celery worker/beat

Properties: - Cross-process and potentially cross-network - Must
interact with L1 exclusively through defined service ports (via Brain
SDK) - Must use Envelopes for all cross-boundary communication

L2 has no direct access to Substrate or Adapters.

------------------------------------------------------------------------

## Layer 1 (L1) -- Services

L1 defines the system's authoritative public service surface.

Properties: - Services are assumed process-local (single
container/process) - Services may call each other directly, but only via
public ports - No service may import another service's internal
implementation - All public interactions must be defined via a Port

L1 is the only layer that: - Owns domain authority - Enforces policy -
Owns audit logs per service domain

------------------------------------------------------------------------

## Layer 0 (L0) -- Substrate & Adapters

L0 contains infrastructure and external integrations.

Substrate examples: - Redis - Object store - Obsidian vault - Letta -
External APIs (Signal, etc.)

Adapters: - Concrete implementations that speak to substrate systems -
Always considered non-local (process/network boundary) - Never directly
accessed outside of the appropriate Authority Service

L0 is never accessed directly by L2. L0 is never accessed directly by
unrelated L1 services.

------------------------------------------------------------------------

# 3. System Model (Within L1)

L1 is organized into three Systems.

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
